# PyInstaller spec — freeze the FastAPI backend as a self-contained desktop sidecar.
# Build:  cd backend && pyinstaller ocd-backend.spec --noconfirm --clean
# Produces a SINGLE self-contained dist/ocd-backend (onefile) so Tauri's externalBin can
# bundle it as one file. The Tauri build script renames it to the target-triple form.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Heavy packages with data files / dynamic imports PyInstaller can't infer statically.
for pkg in ("chromadb",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Our own packages are imported lazily in places (e.g. `from . import integrations`),
# so collect every submodule to be safe.
hiddenimports += collect_submodules("ocd_core")
hiddenimports += collect_submodules("app")

# uvicorn selects its loop/protocol/lifespan impls dynamically at runtime.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["sidecar.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# One-file build: fold binaries + datas into a single self-contained executable so it
# ships as one Tauri sidecar file (no support directory to bundle alongside).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ocd-backend",
    console=True,
    upx=False,
    strip=False,
    disable_windowed_traceback=False,
)
