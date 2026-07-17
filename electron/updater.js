const DEFAULT_CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000;
const DEFAULT_START_DELAY_MS = 15 * 1000;

function updateFeedUrl(backendUrl) {
  return `${backendUrl.replace(/\/$/, '')}/api/desktop-updates`;
}

function configureAutoUpdates({ app, dialog, getMainWindow, backendUrl, logger = console }) {
  if (!app.isPackaged || process.env.GOTBOT_DISABLE_AUTO_UPDATE === '1') {
    logger.info('[GotBotNovel] 自动更新已跳过（非打包环境或被环境变量禁用）');
    return { checkNow: async () => null, stop: () => {} };
  }

  const { autoUpdater } = require('electron-updater');
  const feedUrl = process.env.GOTBOT_UPDATE_FEED_URL || updateFeedUrl(backendUrl);
  const checkIntervalMs = Number(
    process.env.GOTBOT_UPDATE_CHECK_INTERVAL_MS || DEFAULT_CHECK_INTERVAL_MS,
  );
  const startDelayMs = Number(
    process.env.GOTBOT_UPDATE_START_DELAY_MS || DEFAULT_START_DELAY_MS,
  );

  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  // Gitee Release 使用分片文件经本地后端流式拼接，不提供 blockmap 差分下载。
  autoUpdater.disableDifferentialDownload = true;
  autoUpdater.allowPrerelease = false;
  autoUpdater.logger = logger;
  autoUpdater.setFeedURL({ provider: 'generic', url: feedUrl });

  let availableNoticeShown = false;
  let checking = false;
  let stopped = false;

  const setProgress = (value) => {
    const window = getMainWindow();
    if (window && !window.isDestroyed()) {
      window.setProgressBar(value);
    }
  };

  autoUpdater.on('checking-for-update', () => {
    logger.info(`[GotBotNovel] 正在通过 Gitee 检查更新: ${feedUrl}`);
  });

  autoUpdater.on('update-available', (info) => {
    logger.info(`[GotBotNovel] 发现新版本 ${info.version}`);
    if (!availableNoticeShown) {
      availableNoticeShown = true;
      dialog.showMessageBox({
        type: 'info',
        title: '发现新版本',
        message: `GotBotNovel ${info.version} 正在后台下载`,
        detail: '更新文件来自 Gitee。下载完成后会提示是否立即重启安装。',
        buttons: ['我知道了'],
        defaultId: 0,
        noLink: true,
      }).catch((error) => logger.warn('[GotBotNovel] 无法显示更新提示:', error));
    }
  });

  autoUpdater.on('update-not-available', (info) => {
    logger.info(`[GotBotNovel] 当前已是最新版本 ${info.version}`);
  });

  autoUpdater.on('download-progress', (progress) => {
    const ratio = Math.max(0, Math.min(1, progress.percent / 100));
    setProgress(ratio);
    logger.info(
      `[GotBotNovel] 更新下载 ${progress.percent.toFixed(1)}% `
      + `(${progress.transferred}/${progress.total})`,
    );
  });

  autoUpdater.on('update-downloaded', async (info) => {
    setProgress(-1);
    logger.info(`[GotBotNovel] 新版本 ${info.version} 下载完成`);
    const result = await dialog.showMessageBox({
      type: 'info',
      title: '更新已准备好',
      message: `GotBotNovel ${info.version} 已下载完成`,
      detail: '选择“立即重启并更新”会关闭当前窗口并安装；选择“稍后”将在退出应用后安装。',
      buttons: ['立即重启并更新', '稍后'],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    });
    if (result.response === 0) {
      autoUpdater.quitAndInstall(false, true);
    }
  });

  autoUpdater.on('error', (error) => {
    setProgress(-1);
    logger.error('[GotBotNovel] 自动更新失败:', error);
  });

  const checkNow = async () => {
    if (stopped || checking) {
      return null;
    }
    checking = true;
    try {
      return await autoUpdater.checkForUpdates();
    } catch (error) {
      // error 事件会记录具体信息；这里吞掉定时任务异常，避免未处理 Promise。
      return null;
    } finally {
      checking = false;
    }
  };

  const startTimer = setTimeout(() => {
    checkNow();
  }, Number.isFinite(startDelayMs) && startDelayMs >= 0 ? startDelayMs : DEFAULT_START_DELAY_MS);
  const interval = setInterval(
    () => checkNow(),
    Number.isFinite(checkIntervalMs) && checkIntervalMs > 0
      ? checkIntervalMs
      : DEFAULT_CHECK_INTERVAL_MS,
  );

  return {
    checkNow,
    stop: () => {
      stopped = true;
      clearTimeout(startTimer);
      clearInterval(interval);
      setProgress(-1);
    },
  };
}

module.exports = {
  configureAutoUpdates,
  updateFeedUrl,
};
