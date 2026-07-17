# Gitee 桌面自动更新

GotBotNovel 桌面端使用 `electron-updater` 的 generic provider。应用只连接本机后端，
本机后端再从公开的 Gitee Release 获取更新清单和分片，因此运行时不依赖 GitHub。

## 为什么使用分片

桌面安装包包含离线模型和 Python 运行环境，单个文件较大。发布脚本默认把 Windows EXE
和 macOS ZIP 切成 45 MiB 的 Release 附件；本机后端按需拼接并流式返回给
`electron-updater`，最终文件仍由 updater 使用 SHA-512 校验。

## Gitee 仓库要求

1. 创建一个公开仓库，默认地址为 `gitee.com/lyliefeng/GotBotNovel`。
2. Gitee 仓库至少存在 `main` 分支。
3. 创建具有仓库 Release 管理权限的私人令牌。
4. 不要把 Gitee 令牌写入应用或源码；令牌只用于 GitHub Actions 发布。

如仓库路径不同，同时修改：

- GitHub Actions Variables：`GITEE_OWNER`、`GITEE_REPO`、`GITEE_TARGET`。CI 会把
  owner/repo 写入安装包内的 `gotbotUpdate` 配置，并使用同一地址发布 Release。
- 本地手工打包时，先运行：

  ```bash
  node electron/configure-update-source.js <owner> <repo>
  ```

运行时仍可用 `DESKTOP_UPDATE_GITEE_OWNER`、`DESKTOP_UPDATE_GITEE_REPO` 覆盖安装包内配置。

## GitHub Actions Secrets

必须配置：

- `GITEE_ACCESS_TOKEN`
- `MACOS_CSC_LINK`：Developer ID Application 证书的 base64 或安全下载地址
- `MACOS_CSC_KEY_PASSWORD`
- `APPLE_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`
- `APPLE_TEAM_ID`

Windows 签名建议配置：

- `WINDOWS_CSC_LINK`
- `WINDOWS_CSC_KEY_PASSWORD`

标签发布会强制检查 macOS 签名和公证凭据；缺少时不会发布 Gitee 自动更新，避免向用户推送无法安装的 macOS 更新。

## 发布流程

自动更新只接受更高版本。测试构建可以继续保持同一天不提升版本，但不能作为自动更新发布。
正式发布示例：

```bash
# 先把 electron/package.json 的 version 从 1.0.2 改为 1.0.3
git tag v1.0.3
git push origin v1.0.3
```

GitHub Actions 将执行：

1. 在原生 macOS 和 Windows runner 构建安装包。
2. 生成 macOS ZIP、Windows NSIS EXE 和 updater 元数据。
3. 把 ZIP/EXE 切成 45 MiB 分片并生成 `gotbotnovel-update.json`。
4. 创建或更新 Gitee Release，并最后上传更新清单。
5. 已安装应用启动 15 秒后检查更新，之后每 4 小时检查一次。
6. 下载完成后提示用户立即重启安装或稍后安装。

## 可选运行时配置

- `GOTBOT_DISABLE_AUTO_UPDATE=1`：关闭 Electron 自动更新。
- `GOTBOT_UPDATE_FEED_URL`：覆盖本机 generic feed URL，主要用于测试。
- `GOTBOT_UPDATE_START_DELAY_MS`：首次检查延迟。
- `GOTBOT_UPDATE_CHECK_INTERVAL_MS`：定时检查间隔。
- `DESKTOP_UPDATE_ENABLED=false`：关闭后端更新路由。
- `DESKTOP_UPDATE_CACHE_SECONDS`：Gitee Release 元数据缓存时间。

## 当前限制

- 当前版本仍为 `1.0.2`，同版本重新上传不会触发已安装应用更新。
- 已经安装的旧版 `1.0.2` 没有 updater，必须先手动安装包含 updater 的新版安装包。
- macOS 自动更新必须使用 Developer ID 正式签名和 Apple 公证；ad-hoc/未签名包只适合本地测试。
- Gitee 仓库必须公开，因为令牌不能安全地嵌入客户端。
- 截至 2026 年 7 月 17 日，默认地址 `gitee.com/lyliefeng/GotBotNovel` 的公开 API
  返回 404；在创建该仓库并配置 GitHub Actions 凭据前，代码和安装包可以构建，
  但无法完成真实的 Gitee 发布与在线更新验证。
