"""Create the Resolve project and populate its Media Pool from a scan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pathlib import Path

from .binmap import EXTRA_BINS, IMAGE_EXTENSIONS
from .scanner import BinPath, ScanResult

#: Called with a human-readable line of progress.
Progress = Callable[[str], None]

#: Where Resolve writes grade stills for a project. Hidden, matching Resolve's own
#: naming, so a later scan never imports them back in as source media.
GALLERY_DIR_NAME = ".gallery"


class ProjectExists(Exception):
    """A project of this name is already in the current database folder."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(
            f"A project named {name!r} already exists. "
            "Rename it, delete it, or choose a different project name."
        )


class BuildFailed(Exception):
    """Resolve refused an operation we need to succeed."""


@dataclass(frozen=True)
class BuildOptions:
    project_name: str
    width: int = 1920
    height: int = 1080
    fps: str = "25"


@dataclass
class BuildSummary:
    project_name: str
    bins_created: int = 0
    clips_imported: int = 0
    #: Bins Resolve accepted fewer clips for than we handed it.
    short_imports: list[tuple[BinPath, int, int]] = field(default_factory=list)


def _noop(_: str) -> None:
    pass


def _subfolder_by_name(folder, name: str):
    """Return the existing child folder called ``name``, or None.

    Case-insensitive: a project with a ``Voice`` folder on disk should not also
    get a separate ``VOICE`` bin from the standard set.
    """
    target = name.casefold()
    for child in folder.GetSubFolderList() or []:
        if child.GetName().casefold() == target:
            return child
    return None


def _ensure_bin(media_pool, root, path: BinPath, cache: dict[BinPath, object]) -> object:
    """Create (or reuse) the nested bin at ``path``, returning its Folder."""
    if not path:
        return root
    if path in cache:
        return cache[path]

    parent = _ensure_bin(media_pool, root, path[:-1], cache)
    name = path[-1]
    folder = _subfolder_by_name(parent, name) or media_pool.AddSubFolder(parent, name)
    if not folder:
        raise BuildFailed(f"Could not create bin {'/'.join(path)!r}")
    cache[path] = folder
    return folder


def import_files(media_pool, files: list[Path]) -> list:
    """Import one bin's files, returning the MediaPoolItems Resolve created.

    Stills go in one at a time. Handed a batch, Resolve merges consecutively
    numbered images into a single image-sequence clip — so a 188-photo shoot
    becomes one clip and the individual frames are no longer addressable. Camera
    stills are always sequentially numbered, so this is the common case, not an
    edge case: 5,186 images in the reference archive would collapse.

    Video and audio cannot form sequences, so they go in a single call. Importing
    a still costs ~32 ms against ~3 ms batched, which is why the split is worth it.
    """
    stills = [f for f in files if f.suffix.casefold() in IMAGE_EXTENSIONS]
    rest = [f for f in files if f.suffix.casefold() not in IMAGE_EXTENSIONS]

    imported = []
    if rest:
        imported.extend(media_pool.ImportMedia([str(f) for f in rest]) or [])
    for still in stills:
        imported.extend(media_pool.ImportMedia([str(still)]) or [])
    return imported


def build(
    result: ScanResult,
    options: BuildOptions,
    resolve,
    progress: Progress = _noop,
) -> BuildSummary:
    """Create the project, apply settings, build the bin tree, and import media.

    Refuses to touch an existing project of the same name.
    """
    # An open Project Manager window makes every call below return None. Clear it
    # first so callers don't have to remember to.
    from .resolve_api import ensure_ui_ready

    if ensure_ui_ready(resolve):
        progress("Dismissed Resolve's Project Manager window.")

    project_manager = resolve.GetProjectManager()

    existing = project_manager.GetProjectListInCurrentFolder() or []
    if options.project_name in existing:
        raise ProjectExists(options.project_name)

    progress(f"Creating project {options.project_name!r}…")
    project = project_manager.CreateProject(options.project_name)
    if not project:
        # Resolve returns None here with no reason given. In practice it means the
        # UI is busy rather than anything wrong with the name: an open Project
        # Manager window or a modal dialog blocks scripted project creation, and
        # every ProjectManager method starts returning None while that is true.
        raise BuildFailed(
            f"Resolve would not create project {options.project_name!r}.\n"
            "This usually means Resolve's UI is blocking scripting. Check that:\n"
            "  1. The Project Manager window is closed, and\n"
            "  2. No dialog is waiting for an answer (save prompts, warnings).\n"
            "Then try again — nothing has been changed."
        )

    _apply_settings(project, options, progress)
    apply_working_folders(project, result.root, progress)

    media_pool = project.GetMediaPool()
    root = media_pool.GetRootFolder()
    cache: dict[BinPath, object] = {}
    summary = BuildSummary(project_name=options.project_name)

    progress(f"Building {result.bin_count} bins…")
    for bin_path, files in result.bins.items():
        folder = _ensure_bin(media_pool, root, bin_path, cache)

        if not media_pool.SetCurrentFolder(folder):
            raise BuildFailed(f"Could not select bin {'/'.join(bin_path)!r}")

        imported = import_files(media_pool, files)
        summary.clips_imported += len(imported)
        if len(imported) != len(files):
            summary.short_imports.append((bin_path, len(files), len(imported)))

        progress(f"  {'/'.join(bin_path)} — {len(imported)}/{len(files)} clips")

    # Project folders that held no importable media, then the standard set. Both
    # go through _ensure_bin, which reuses a bin already created above rather than
    # duplicating it.
    for bin_path in result.empty_bins:
        _ensure_bin(media_pool, root, bin_path, cache)
    if result.empty_bins:
        progress(f"Empty folders: {', '.join(b[-1] for b in result.empty_bins)}")

    for name in EXTRA_BINS:
        _ensure_bin(media_pool, root, (name,), cache)
    progress(f"Standard bins: {', '.join(EXTRA_BINS)}")

    summary.bins_created = len(cache)

    media_pool.SetCurrentFolder(root)
    project_manager.SaveProject()
    progress("Saved.")
    return summary


def apply_working_folders(project, root: Path, progress: Progress = _noop) -> list[str]:
    """Point Resolve's per-project working folders at this project's own folder.

    Resolve inherits these from whichever project was open last, so a new project
    quietly keeps another project's paths — a freshly created project here was
    still pointing ``projectMediaLocation`` at an unrelated project's folder.

    ``perfCacheClipsLocation`` is deliberately left alone: cache is kept in one
    shared location on purpose so it can be cleared in a single sweep.

    Returns the names of any settings Resolve refused.
    """
    gallery = root / GALLERY_DIR_NAME
    try:
        gallery.mkdir(exist_ok=True)
    except OSError as exc:
        progress(f"  warning: could not create {gallery}: {exc}")

    settings = {
        "projectMediaLocation": str(root),
        "colorGalleryStillsLocation": str(gallery),
    }
    rejected = [key for key, value in settings.items() if not project.SetSetting(key, value)]

    progress(f"Working folders -> {root}")
    progress(f"  gallery stills -> {gallery}")
    progress("  cache location left as-is")
    if rejected:
        progress(f"  warning: Resolve rejected {', '.join(rejected)}")
    return rejected


def _apply_settings(project, options: BuildOptions, progress: Progress) -> None:
    """Set timeline resolution and frame rate, reporting anything Resolve rejects."""
    settings = {
        "timelineResolutionWidth": str(options.width),
        "timelineResolutionHeight": str(options.height),
        "timelineOutputResolutionWidth": str(options.width),
        "timelineOutputResolutionHeight": str(options.height),
        "timelineFrameRate": str(options.fps),
    }
    rejected = [key for key, value in settings.items() if not project.SetSetting(key, value)]
    progress(f"Set {options.width}x{options.height} @ {options.fps} fps")
    if rejected:
        progress(f"  warning: Resolve rejected {', '.join(rejected)}")
