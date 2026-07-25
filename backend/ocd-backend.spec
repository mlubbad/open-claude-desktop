# PyInstaller spec — freeze the FastAPI backend as a self-contained desktop sidecar.
# Build:  cd backend && pyinstaller ocd-backend.spec --noconfirm --clean
# Produces a SINGLE self-contained dist/ocd-backend (onefile) so Tauri's externalBin can
# bundle it as one file. The Tauri build script renames it to the target-triple form.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Bundled, immutable marketplace catalog. ocd_core.config resolves MARKETPLACE_DIR to
# "content/marketplace" under sys._MEIPASS when frozen; installs COPY out of the bundle
# into the writable per-user PLUGINS_DIR, never into the bundle. SPECPATH is backend/.
datas += [(str(Path(SPECPATH).resolve().parent / "content" / "marketplace"),
           "content/marketplace")]

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
# A dev-machine build runs from a used checkout where loading the catalog has left
# content/marketplace/__pycache__ behind — never ship stale bytecode as data files.
a.datas = [d for d in a.datas if "__pycache__" not in d[0]]
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
