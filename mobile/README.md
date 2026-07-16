# GotBotNovel Android 客户端

这个目录使用 Capacitor 将 GotBotNovel 前端封装为 Android 客户端。

## 本地构建

```bash
cd frontend
npm ci
npm run build

cd ../mobile
npm ci
npm run sync
cd android
./gradlew assembleDebug
```

生成的 APK 位于 `mobile/android/app/build/outputs/apk/debug/`。

## 后端地址

默认情况下，客户端使用随包静态页面；要让 Android 客户端连接一个 GotBotNovel 后端，构建时设置：

```bash
GOTBOT_SERVER_URL=https://your-gotbotnovel-server.example npm run sync
```

配置远程地址后，Capacitor WebView 会直接加载该地址，前端的相对 `/api` 请求也会指向该后端。发布 APK 前必须使用实际可访问的 HTTPS 后端地址；本仓库不会把任何个人服务器地址或密钥写入源码。
