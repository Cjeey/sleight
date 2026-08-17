# PyInstaller recipe for Sleyth.app
#
# mediapipe is the awkward one: it ships .tflite/.binarypb model files and
# native .so modules that PyInstaller cannot infer, so they are collected
# explicitly. The hand model itself is bundled too - a first run should not
# need the network.
from PyInstaller.utils.hooks import collect_all

# collect_all, not collect_data_files: mediapipe imports much of itself
# dynamically, so static analysis finds almost none of it. Collecting the
# .so alone gives an app that builds cleanly and then cannot import it.
mp_datas, mp_binaries, mp_hidden = collect_all("mediapipe")
datas = mp_datas + [("hand_landmarker.task", ".")]
binaries = mp_binaries

a = Analysis(
    ["sleyth.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=mp_hidden + [
        "mediapipe",
        "mediapipe.python._framework_bindings",
        "AppKit", "Quartz", "Foundation", "objc",
        "ApplicationServices",
        "glass",
    ],
    hookspath=[],
    runtime_hooks=[],
    # NOTE: matplotlib must NOT be excluded. mediapipe.solutions.drawing_utils
    # imports it at module load, and mediapipe/__init__ imports solutions - so
    # excluding it builds an app that cannot import mediapipe at all.
    # jaxlib alone is 239MB - pulled in transitively by mediapipe and never
    # touched by hand tracking. Dropping it and friends halves the download.
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6",
              "IPython", "jupyter", "pytest", "pandas", "torch",
              "tensorflow", "jax", "jaxlib", "scipy", "sentencepiece",
              "ml_dtypes", "opt_einsum"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Sleyth",
          debug=False, strip=False, upx=False, console=False,
          argv_emulation=False)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Sleyth")

app = BUNDLE(
    coll,
    name="Sleyth.app",
    icon=None,
    bundle_identifier="com.sleyth.app",
    info_plist={
        # macOS refuses camera access outright without this string, and the
        # text is what the permission dialog shows the user.
        "NSCameraUsageDescription":
            "Sleyth watches your hand to move the cursor. Video never "
            "leaves your Mac and is never recorded.",
        "NSMicrophoneUsageDescription": "Not used.",
        "LSMinimumSystemVersion": "12.0",
        "CFBundleShortVersionString": "7.8",
        "CFBundleVersion": "7.8",
        "LSApplicationCategoryType": "public.app-category.utilities",
        # accessory: no Dock icon, the widget and menu bar ARE the app
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
