# GotBotNovel 桌面壳

该目录提供 Electron macOS 壳的最小运行骨架：

- 开发模式默认从仓库中的 `backend/` 启动 Uvicorn；
- 打包模式优先启动 `resources/backend_bin/gotbotnovel-backend`；
- 后端健康检查通过后，窗口加载 FastAPI 托管的前端；
- SQLite 数据放在 Electron 的用户数据目录，不写入应用包；
- `resources/embedding_model/` 是桌面包内直接展开、无符号链接的离线 embedding 模型目录。

## 当前状态

Electron 打包工作流会下载 embedding 模型、构建 PyInstaller 后端，并生成可分发的 `.dmg` 或 Windows 便携包。Windows 产物包含 `GotBotNovel-windows-x64.exe` 和配套的 `GotBotNovel-windows-x64.zip`；模型使用直接路径加载，桌面运行不依赖联网下载模型。

## 开发运行

```bash
npm install
npm run dev
```

如需使用指定后端可执行文件：

```bash
GOTBOT_BACKEND_BIN=/absolute/path/to/gotbotnovel-backend npm run dev
```
