# GotBotNovel 桌面壳

该目录提供 Electron macOS 壳的最小运行骨架：

- 开发模式默认从仓库中的 `backend/` 启动 Uvicorn；
- 打包模式优先启动 `resources/backend_bin/gotbotnovel-backend`；
- 后端健康检查通过后，窗口加载 FastAPI 托管的前端；
- SQLite 数据放在 Electron 的用户数据目录，不写入应用包；
- `resources/embedding_onnx/` 是后续 ONNX 模型产物目录。

## 当前状态

Electron 依赖和后端可执行文件尚未在本阶段构建，因此目前只提交壳的启动逻辑和打包配置。生成可分发 `.app/.dmg` 前，还需要完成 ONNX embedding 适配、PyInstaller 构建和 Electron 依赖安装验证。

## 开发运行

```bash
npm install
npm run dev
```

如需使用指定后端可执行文件：

```bash
GOTBOT_BACKEND_BIN=/absolute/path/to/gotbotnovel-backend npm run dev
```
