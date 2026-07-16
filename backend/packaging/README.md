# Desktop backend packaging

Desktop builds use PyInstaller to bundle the FastAPI backend into a platform-native executable. The Electron shell starts that executable and keeps the SQLite database in Electron's per-user data directory.

The executable is intentionally built in GitHub Actions on the target operating system. PyInstaller executables are not cross-compiled reliably between macOS, Windows, and Linux.
