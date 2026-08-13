# PyInstaller spec for Resolve Ingest.
#
# Build from the repo root:
#     pyinstaller packaging/resolve-ingest.spec --noconfirm
#
#   macOS   -> dist/Resolve Ingest.app
#   Windows -> dist/Resolve Ingest.exe          (GUI, one self-contained file)
#              dist/Resolve Ingest (console).exe (same app, keeps a console open)
#
# PyInstaller cannot cross-compile: the Windows build has to run on Windows.
# .github/workflows/build-windows.yml does that on a hosted runner.
#
# Note: DaVinciResolveScript and fusionscript are deliberately NOT bundled. They
# belong to the user's Resolve install and are loaded at runtime by
# resolve_ingest.resolve_api, which finds them per-platform. Bundling a copy would
# pin us to one Resolve version.

import sys
from pathlib import Path

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")

HERE = Path(SPECPATH)
SRC = str(HERE.parent / "src")

# Generated from icon.png by make_icons.py, both committed so a build needs
# neither Pillow nor a Mac.
ICNS = str(HERE / "icon.icns")
ICO = str(HERE / "icon.ico")

analysis = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=["resolve_ingest.cli", "resolve_ingest.builder"],
    hookspath=[],
    runtime_hooks=[],
    # Trim the parts of the stdlib PyInstaller pulls in but we never touch.
    excludes=["pytest", "numpy", "matplotlib", "PIL", "unittest", "pydoc_data"],
    noarchive=False,
)

pyz = PYZ(analysis.pure, analysis.zipped_data)

if IS_WINDOWS:
    # One file, so there is a single thing to send someone.
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="Resolve Ingest",
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon=ICO,
    )

    # A Windows GUI executable is detached from the console, so the dual-mode CLI
    # prints into the void when run with arguments. This second build keeps its
    # console, which is how you get a readable error out of a machine where the
    # Resolve paths have never been verified.
    exe_console = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="Resolve Ingest (console)",
        debug=False,
        strip=False,
        upx=False,
        console=True,
        icon=ICO,
    )

else:
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="Resolve Ingest",
        debug=False,
        strip=False,
        upx=False,
        console=False,
        # Apple silicon only; use "universal2" if you need Intel Macs too, which
        # requires a universal2 Python build.
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    collect = COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        name="Resolve Ingest",
    )

    if IS_MACOS:
        app = BUNDLE(
            collect,
            name="Resolve Ingest.app",
            icon=ICNS,
            bundle_identifier="no.sandenmedia.resolve-ingest",
            info_plist={
                "CFBundleShortVersionString": "0.1.0",
                "NSHighResolutionCapable": True,
                # Footage lives on external and network volumes; without these the
                # app is silently denied access and every scan comes back empty.
                "NSDesktopFolderUsageDescription": "Resolve Ingest reads footage from your project folder.",
                "NSDocumentsFolderUsageDescription": "Resolve Ingest reads footage from your project folder.",
                "NSRemovableVolumesUsageDescription": "Resolve Ingest reads footage from external drives.",
                "NSNetworkVolumesUsageDescription": "Resolve Ingest reads footage from network drives.",
            },
        )
