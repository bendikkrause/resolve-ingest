"""Locate and load DaVinci Resolve's Python scripting module.

A standalone app cannot assume the user has ``RESOLVE_SCRIPT_API`` and friends
exported in their shell — an app launched from Finder or the Start menu inherits
almost no environment. So we find Resolve ourselves, and only fall back to the
environment when it has been set deliberately.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path


class ResolveNotFound(Exception):
    """Resolve's scripting API could not be located on this machine."""


class ResolveNotRunning(Exception):
    """Resolve is installed but not reachable.

    Almost always one of: Resolve is not running, or Studio's
    Preferences > General > "External scripting using" is not set to Local.
    """


class ResolveBusy(Exception):
    """Resolve's UI is blocking scripting and we could not clear it."""


@dataclass(frozen=True)
class ResolvePaths:
    api: Path
    lib: Path

    @property
    def modules(self) -> Path:
        return self.api / "Modules"

    def missing(self) -> list[Path]:
        return [p for p in (self.api, self.lib, self.modules) if not p.exists()]


def default_paths() -> ResolvePaths:
    """Standard install locations for the current platform.

    macOS paths are verified against a real Resolve Studio 21.0.3 install.
    Windows and Linux paths follow Blackmagic's documented layout.
    """
    if sys.platform == "darwin":
        return ResolvePaths(
            api=Path(
                "/Library/Application Support/Blackmagic Design/DaVinci Resolve"
                "/Developer/Scripting"
            ),
            lib=Path(
                "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents"
                "/Libraries/Fusion/fusionscript.so"
            ),
        )
    if sys.platform.startswith("win"):
        program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        return ResolvePaths(
            api=program_data
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Developer"
            / "Scripting",
            lib=program_files
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "fusionscript.dll",
        )
    return ResolvePaths(
        api=Path("/opt/resolve/Developer/Scripting"),
        lib=Path("/opt/resolve/libs/Fusion/fusionscript.so"),
    )


def resolve_paths() -> ResolvePaths:
    """Install paths, letting a deliberately-set environment win."""
    defaults = default_paths()
    return ResolvePaths(
        api=Path(os.environ.get("RESOLVE_SCRIPT_API") or defaults.api),
        lib=Path(os.environ.get("RESOLVE_SCRIPT_LIB") or defaults.lib),
    )


def ensure_ui_ready(resolve) -> bool:
    """Clear Resolve's Project Manager window if it is blocking scripting.

    While that window is open, *every* ProjectManager method returns None —
    ``CreateProject``, ``GotoRootFolder``, and even read-only calls like
    ``GetCurrentFolder`` and ``GetCurrentDatabase``. Nothing in the error says so,
    which makes it look like the project name was rejected.

    ``GetCurrentPage()`` is the tell. Returning None is documented behaviour, not a
    fault: the main window simply isn't showing a page, which is exactly the
    Project Manager state. Switching to a page dismisses it.

    Returns True if it had to intervene, False if Resolve was already usable.
    Raises :class:`ResolveBusy` if the block persists.
    """
    if resolve.GetCurrentPage() is not None:
        return False

    resolve.OpenPage("media")

    if resolve.GetCurrentPage() is None:
        # OpenPage was refused too. Resolve accepts read-only calls in this state
        # (GetCurrentProject still answers) but silently drops every write, so
        # there is nothing more scripting can do — a person has to clear the UI.
        raise ResolveBusy(
            "DaVinci Resolve is not accepting scripted commands.\n"
            "It answers read-only calls but silently ignores every change, which "
            "means its interface is holding them. Usually one of:\n"
            "  1. The Project Manager window is open — open a project, or close it.\n"
            "  2. A dialog is waiting for an answer (save prompt, warning, "
            "media offline).\n"
            "Clear it in Resolve, then run again. Nothing has been changed."
        )
    return True


def connect():
    """Return a connected Resolve application object.

    Raises :class:`ResolveNotFound` if Resolve isn't installed where we expect,
    or :class:`ResolveNotRunning` if it is installed but won't answer.
    """
    paths = resolve_paths()
    missing = paths.missing()
    if missing:
        raise ResolveNotFound(
            "Could not find DaVinci Resolve's scripting API. Missing:\n"
            + "\n".join(f"  {p}" for p in missing)
        )

    # DaVinciResolveScript reads these at import time to dlopen fusionscript.
    os.environ["RESOLVE_SCRIPT_API"] = str(paths.api)
    os.environ["RESOLVE_SCRIPT_LIB"] = str(paths.lib)

    module_name = "DaVinciResolveScript"
    module_path = paths.modules / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ResolveNotFound(f"Could not load {module_path}")

    module = importlib.util.module_from_spec(spec)
    # DaVinciResolveScript.py ends with `sys.modules[__name__] = script_module`,
    # swapping itself for the native fusionscript extension. A normal `import`
    # picks that up because the import machinery re-reads sys.modules afterwards;
    # exec_module does not, so we must register the name first and then re-read it.
    # Skipping this leaves us holding the empty shell module, which has no scriptapp.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except ImportError as exc:
        del sys.modules[module_name]
        raise ResolveNotFound(
            f"Resolve's scripting module could not load {paths.lib}: {exc}"
        ) from exc
    module = sys.modules[module_name]

    resolve = module.scriptapp("Resolve")
    if resolve is None:
        raise ResolveNotRunning(
            "DaVinci Resolve did not respond. Check that:\n"
            "  1. Resolve is running, and\n"
            "  2. Preferences > General > 'External scripting using' is set to Local."
        )
    return resolve
