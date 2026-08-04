"""Walk a project root and work out which footage belongs in which Resolve bin.

Like :mod:`resolve_ingest.binmap`, this has no Resolve dependency — a scan can be
run and inspected with Resolve closed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .binmap import (
    FOOTAGE_ROOT_NAME,
    bin_path_for,
    footage_root_tier,
    is_excluded_folder,
    is_media_file,
)

BinPath = tuple[str, ...]


class FootageRootMissing(Exception):
    """The project root has no recognisable footage folder."""

    def __init__(self, root: Path):
        self.root = root
        super().__init__(
            f"No footage folder found in {root}.\n"
            f"Expected a folder named {FOOTAGE_ROOT_NAME!r} (or the older "
            f"'01 ORIGINALOPPTAK' / 'Originale opptak' form).\n"
            "If the folder is named something else, point at it directly."
        )


class AmbiguousFootageRoot(Exception):
    """Several folders look equally like the footage root, so we won't guess."""

    def __init__(self, root: Path, candidates: list[Path]):
        self.root = root
        self.candidates = candidates
        names = "\n".join(f"  {c.name}" for c in candidates)
        super().__init__(
            f"More than one folder in {root} looks like the footage folder:\n"
            f"{names}\n"
            "Point at the right one directly."
        )


@dataclass(frozen=True)
class ScanResult:
    root: Path
    project_name: str
    #: Bin path -> media files that belong in it, both in sorted order.
    bins: dict[BinPath, list[Path]] = field(default_factory=dict)
    #: Project folders that hold no importable media but should still become bins,
    #: so a "Stills" folder of .psd files doesn't just vanish from the project.
    empty_bins: tuple[BinPath, ...] = ()
    #: Folders skipped by name — reported so a wrong exclusion is visible, not silent.
    excluded: tuple[str, ...] = ()
    #: Directories that could not be read (permissions, unmounted volume, ...).
    unreadable: list[Path] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(len(files) for files in self.bins.values())

    @property
    def bin_count(self) -> int:
        return len(self.bins)


def find_footage_root(root: Path, override: str | Path | None = None) -> Path:
    """Locate the footage folder directly under ``root``.

    ``override`` names a folder explicitly — for the projects that follow neither
    convention. It may be a bare folder name or an absolute path.

    Otherwise the best-scoring direct child wins (see
    :func:`~resolve_ingest.binmap.footage_root_tier`). Two equally good candidates
    raise rather than picking one arbitrarily; silently importing the wrong tree is
    worse than asking.
    """
    if override:
        candidate = Path(override)
        if not candidate.is_absolute():
            candidate = root / candidate
        # Bins are named by their path relative to the project root, so a footage
        # folder outside it has no representable name.
        if not candidate.is_dir() or root not in candidate.resolve().parents:
            raise FootageRootMissing(root)
        return candidate

    try:
        entries = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError as exc:
        raise FootageRootMissing(root) from exc

    best: int | None = None
    matches: list[Path] = []
    for entry in entries:
        tier = footage_root_tier(entry.name)
        if tier is None:
            continue
        if best is None or tier < best:
            best, matches = tier, [entry]
        elif tier == best:
            matches.append(entry)

    if not matches:
        raise FootageRootMissing(root)
    if len(matches) > 1:
        raise AmbiguousFootageRoot(root, matches)
    return matches[0]


def scan(root: Path, footage_root: str | Path | None = None) -> ScanResult:
    """Group every media file in the project by its target bin.

    Everything in the project root is scanned, not just the footage folder —
    ``Stills``, ``Musikk``, ``Arkivbilder`` and the like become bins too. Folders
    in :data:`~resolve_ingest.binmap.EXCLUDED_FOLDERS` are skipped, as are hidden
    ones such as ``.blackmagicsync-v2``.

    A recognisable footage folder is still required. It is what distinguishes a
    project root from any other folder, and without that check pointing at the
    wrong directory would quietly produce a nonsense project.
    """
    root = Path(root).expanduser().resolve()
    find_footage_root(root, footage_root)

    bins: dict[BinPath, list[Path]] = {}
    empty_bins: list[BinPath] = []
    excluded: list[str] = []
    unreadable: list[Path] = []

    def on_error(exc: OSError) -> None:
        unreadable.append(Path(getattr(exc, "filename", str(root))))

    try:
        children = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError as exc:
        raise FootageRootMissing(root) from exc

    for child in children:
        if child.name.startswith("."):
            continue
        if is_excluded_folder(child.name):
            excluded.append(child.name)
            continue

        found = False
        for dirpath, dirnames, filenames in os.walk(child, onerror=on_error):
            # Prune in place so os.walk never descends into these at all. Excluded
            # names apply at every depth, not just the project root: camera
            # thumbnail folders (THMBNL) live deep inside the card structure.
            dirnames[:] = sorted(
                d
                for d in dirnames
                if not d.startswith(".") and not is_excluded_folder(d)
            )

            media = [f for f in filenames if is_media_file(f)]
            if not media:
                continue

            current = Path(dirpath)
            target = bin_path_for(current.relative_to(root))
            bins.setdefault(target, []).extend(current / name for name in media)
            found = True

        if not found:
            empty_bins.append((child.name,))

    for files in bins.values():
        files.sort()

    return ScanResult(
        root=root,
        project_name=root.name,
        bins={key: bins[key] for key in sorted(bins)},
        empty_bins=tuple(empty_bins),
        excluded=tuple(excluded),
        unreadable=unreadable,
    )


def format_tree(result: ScanResult) -> str:
    """Render a scan as an indented bin tree with per-bin file counts."""
    lines = [
        f"Project:  {result.project_name}",
        f"Root:     {result.root}",
        f"Bins:     {result.bin_count}",
        f"Files:    {result.file_count}",
        "",
    ]

    seen: set[BinPath] = set()
    for bin_path in result.empty_bins:
        seen.add(bin_path)
        lines.append(f"{bin_path[-1]}/  (empty)")

    for bin_path, files in result.bins.items():
        # Emit any intermediate bins that hold no media of their own.
        for depth in range(1, len(bin_path) + 1):
            prefix = bin_path[:depth]
            if prefix in seen:
                continue
            seen.add(prefix)
            indent = "  " * (depth - 1)
            count = len(files) if depth == len(bin_path) else 0
            suffix = f"  ({count} clips)" if count else ""
            lines.append(f"{indent}{prefix[-1]}/{suffix}")

    if result.excluded:
        lines.append("")
        lines.append(f"Skipped: {', '.join(result.excluded)}")

    if result.unreadable:
        lines.append("")
        lines.append(f"Unreadable directories: {len(result.unreadable)}")
        for path in result.unreadable[:10]:
            lines.append(f"  {path}")

    return "\n".join(lines)
