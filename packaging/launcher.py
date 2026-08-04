"""Frozen-app entry point.

PyInstaller runs its entry script as ``__main__`` with no package context, so
pointing it straight at ``src/resolve_ingest/gui.py`` breaks that module's
relative imports. Importing the package properly here keeps them working.

Double-clicked (no arguments) the bundle opens the window; run from a terminal
with arguments it behaves as the CLI. That makes the packaged build scriptable,
and lets the frozen binary be tested end-to-end without driving the GUI.
"""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from resolve_ingest.cli import main
    else:
        from resolve_ingest.gui import main
    raise SystemExit(main())
