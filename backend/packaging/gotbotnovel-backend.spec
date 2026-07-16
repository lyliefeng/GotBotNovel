# PyInstaller spec used by the desktop CI workflow.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


packaging_root = Path(SPECPATH).resolve()
backend_root = packaging_root.parent
sys.path.insert(0, str(backend_root))

datas = [
    (str(backend_root / "alembic"), "alembic"),
    (str(backend_root / "alembic-sqlite.ini"), "."),
    (str(backend_root / "static"), "static"),
]
binaries = []
hiddenimports = [
    *collect_submodules("app"),
    *collect_submodules("uvicorn"),
    "aiosqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
]

for package in ("chromadb", "sentence_transformers", "transformers", "mcp"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


analysis = Analysis(
    [str(packaging_root / "run_backend.py")],
    pathex=[str(backend_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    name="gotbotnovel-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    exclude_binaries=True,
)
coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="gotbotnovel-backend",
)
