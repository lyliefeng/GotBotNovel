# Desktop backend packaging

Desktop builds use PyInstaller to bundle the FastAPI backend into a platform-native executable. The Electron shell starts that executable and keeps the SQLite database in Electron's per-user data directory.

The executable is intentionally built in GitHub Actions on the target operating system. PyInstaller executables are not cross-compiled reliably between macOS, Windows, and Linux.

## Gitee desktop auto-update publishing

`prepare_gitee_update.py` splits the Windows NSIS installer and macOS updater ZIP into 45 MiB chunks and writes `gotbotnovel-update.json`.

`publish_gitee_release.py` keeps the Windows chunks and manifest in the stable `<tag>` Release. The larger macOS updater ZIP is stored in a prerelease named `<tag>-macos-arm64`; its manifest entry contains a `releaseTag` reference. This avoids Gitee's observed single-Release capacity boundary while keeping `/releases/latest` and the public version tag on the stable release.

The backend `/api/desktop-updates` route reads the stable manifest, loads referenced auxiliary Release attachments when needed, and streams the verified chunks as standard `electron-updater` files.
