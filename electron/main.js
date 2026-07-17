const { app, BrowserWindow, dialog, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');
const packageMetadata = require('./package.json');
const { configureAutoUpdates } = require('./updater');

const APP_NAME = 'GotBotNovel';
const BACKEND_PORT = Number(process.env.GOTBOT_BACKEND_PORT || 8000);
const BACKEND_HOST = process.env.GOTBOT_BACKEND_HOST || '127.0.0.1';
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`;
const HEALTH_TIMEOUT_MS = Number(process.env.GOTBOT_HEALTH_TIMEOUT_MS || 90_000);
const UPDATE_CONFIG = packageMetadata.gotbotUpdate || {};

let mainWindow = null;
let backendProcess = null;
let updateController = null;

function packagedResource(...parts) {
  return path.join(process.resourcesPath, ...parts);
}

function runtimeDataDir() {
  return path.join(app.getPath('userData'), 'data');
}

function backendEnvironment() {
  const dataDir = runtimeDataDir();
  fs.mkdirSync(dataDir, { recursive: true });

  return {
    ...process.env,
    APP_NAME,
    APP_VERSION: app.getVersion(),
    APP_HOST: BACKEND_HOST,
    APP_PORT: String(BACKEND_PORT),
    DATABASE_URL: `sqlite+aiosqlite:///${path.join(dataDir, 'gotbotnovel.db')}`,
    ONNX_EMBEDDING_DIR: packagedResource('embedding_model'),
    GOTBOT_STATIC_DIR: packagedResource('static'),
    GOTBOT_EMBEDDING_MODEL_DIR: packagedResource('embedding_model'),
    SENTENCE_TRANSFORMERS_HOME: packagedResource('embedding_model'),
    TRANSFORMERS_OFFLINE: '1',
    HF_HUB_OFFLINE: '1',
    DESKTOP_UPDATE_GITEE_API_BASE:
      process.env.DESKTOP_UPDATE_GITEE_API_BASE || UPDATE_CONFIG.giteeApiBase || 'https://gitee.com/api/v5',
    DESKTOP_UPDATE_GITEE_OWNER:
      process.env.DESKTOP_UPDATE_GITEE_OWNER || UPDATE_CONFIG.giteeOwner || 'lv-liefeng',
    DESKTOP_UPDATE_GITEE_REPO:
      process.env.DESKTOP_UPDATE_GITEE_REPO || UPDATE_CONFIG.giteeRepo || 'GotBotNovel',
  };
}

function startBackend() {
  if (process.env.GOTBOT_SKIP_BACKEND === '1') {
    return null;
  }

  const env = backendEnvironment();
  const configuredBinary = process.env.GOTBOT_BACKEND_BIN;
  const binaryName = process.platform === 'win32'
    ? 'gotbotnovel-backend.exe'
    : 'gotbotnovel-backend';
  const packagedBinary = packagedResource('backend_bin', binaryName);

  if (configuredBinary || (app.isPackaged && fs.existsSync(packagedBinary))) {
    const binary = configuredBinary || packagedBinary;
    backendProcess = spawn(binary, [], {
      cwd: process.resourcesPath,
      env,
      stdio: 'inherit',
    });
  } else {
    const backendRoot = path.resolve(__dirname, '..', 'backend');
    const python = process.env.PYTHON_BIN || 'python3';
    backendProcess = spawn(
      python,
      ['-m', 'uvicorn', 'app.main:app', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT)],
      { cwd: backendRoot, env, stdio: 'inherit' },
    );
  }

  backendProcess.on('error', (error) => {
    console.error(`[${APP_NAME}] 后端启动失败:`, error);
  });
  backendProcess.on('exit', (code, signal) => {
    if (code !== 0 && signal !== 'SIGTERM') {
      console.error(`[${APP_NAME}] 后端退出: code=${code}, signal=${signal}`);
    }
  });

  return backendProcess;
}

function healthCheck() {
  return new Promise((resolve) => {
    const request = http.get(`${BACKEND_URL}/health`, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on('error', () => resolve(false));
    request.setTimeout(2_000, () => {
      request.destroy();
      resolve(false);
    });
  });
}

async function waitForBackend() {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await healthCheck()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`后端在 ${HEALTH_TIMEOUT_MS}ms 内未通过健康检查: ${BACKEND_URL}/health`);
}

async function showMacOSPermissionNotice() {
  if (process.platform !== 'darwin') {
    return;
  }

  const noticeFile = path.join(app.getPath('userData'), `macos-permission-notice-${app.getVersion()}`);
  if (fs.existsSync(noticeFile)) {
    return;
  }

  const result = await dialog.showMessageBox({
    type: 'info',
    title: 'macOS 权限提示',
    message: '首次运行可能需要确认本地网络和文件夹访问权限',
    detail: [
      'GotBotNovel 会在本机 127.0.0.1 启动配套服务，macOS 如询问本地网络权限，请选择“允许”。',
      '导入或导出文件到桌面、文稿或下载目录时，macOS 可能单独询问文件夹访问权限。',
      '如果系统阻止打开应用，请前往“系统设置 → 隐私与安全性”，确认后选择“仍要打开”。',
    ].join('\n\n'),
    buttons: ['我知道了', '打开隐私与安全性设置'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  });

  try {
    fs.writeFileSync(noticeFile, new Date().toISOString(), { mode: 0o600 });
  } catch (error) {
    console.warn(`[${APP_NAME}] 无法保存 macOS 权限提示状态:`, error);
  }

  if (result.response === 1) {
    await shell.openExternal('x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension');
  }
}

async function createWindow() {
  startBackend();
  await waitForBackend();
  await showMacOSPermissionNotice();

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1024,
    minHeight: 720,
    title: APP_NAME,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.removeMenu();
  await mainWindow.loadURL(process.env.GOTBOT_FRONTEND_URL || BACKEND_URL);
  mainWindow.once('ready-to-show', () => mainWindow.show());

  if (!updateController) {
    updateController = configureAutoUpdates({
      app,
      dialog,
      getMainWindow: () => mainWindow,
      backendUrl: BACKEND_URL,
      logger: console,
    });
  }
}

function stopBackend() {
  if (backendProcess && !backendProcess.killed) {
    backendProcess.kill('SIGTERM');
    backendProcess = null;
  }
}

app.whenReady().then(async () => {
  try {
    await createWindow();
  } catch (error) {
    console.error(`[${APP_NAME}] 桌面应用启动失败:`, error);
    stopBackend();
    app.quit();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow().catch((error) => console.error(`[${APP_NAME}] 窗口恢复失败:`, error));
    }
  });
});

app.on('before-quit', () => {
  if (updateController) {
    updateController.stop();
    updateController = null;
  }
  stopBackend();
});
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
