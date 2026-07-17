# Desktop backend packaging

Desktop builds use PyInstaller to bundle the FastAPI backend into a platform-native executable. The Electron shell starts that executable and keeps the SQLite database in Electron's per-user data directory.

The executable is intentionally built in GitHub Actions on the target operating system. PyInstaller executables are not cross-compiled reliably between macOS, Windows, and Linux.

## Gitee desktop auto-update publishing

`prepare_gitee_update.py` splits the Windows NSIS installer and macOS updater ZIP into 45 MiB chunks and writes `gotbotnovel-update.json`.

Gitee's API currently enforces a 1 GB Release-attachment quota per repository. `publish_gitee_release.py` therefore keeps the Windows chunks and manifest in the public `GotBotNovel` repository, while macOS chunks are stored in the public `GotBotNovel-Updates-macOS` repository. The macOS manifest entry records `releaseOwner`, `releaseRepo`, and `releaseTag`.

Before publishing a new version, the publisher removes managed update attachments from older Releases so each repository remains below its quota. The stable Release is kept as a prerelease until all Windows chunks and the final manifest are uploaded.

The backend `/api/desktop-updates` route reads the stable manifest, loads referenced cross-repository Release attachments when needed, and streams the verified chunks as standard `electron-updater` files.
