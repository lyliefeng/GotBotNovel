# PyInstaller spec used by the desktop CI workflow.
from PyInstaller.utils.hooks import collect_all, collect_submodules


datas = [
    ("../alembic", "alembic"),
    ("../static", "static"),
]
binaries = []
hiddenimports = [
    *collect_submodules("app"),
    *collect_submodules("uvicorn"),
]

for package in ("chromadb", "sentence_transformers", "transformers", "mcp"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports


analysis = Analysis(
    ["run_backend.py"],
    pathex=[".."],
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
