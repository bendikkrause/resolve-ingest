"""Mapping from on-disk footage paths to DaVinci Resolve bin paths.

Pure functions only — nothing here imports or touches Resolve, so the rules can be
tested exhaustively against a real footage archive without Resolve running.

Footage is stored with the camera's own card structure intact (it is kept so media
can be recovered if a file is corrupt), but that structure is noise inside Resolve.
``Opptak/Interview/FX3/private/M4ROOT/CLIP`` should become the bin
``Opptak/Interview/FX3``.
"""

from __future__ import annotations

import re
from pathlib import PurePath

#: The current convention, and what gets shown in UI hints.
FOOTAGE_ROOT_NAME = "Opptak"

#: Footage-root folder names, in priority order — the first tier that matches any
#: direct child of the project root wins.
#:
#: Matching is deliberately anchored rather than a substring search. Plenty of
#: folders contain "opptak" without being the footage root ("Mobilopptak",
#: "Droneopptak", "Telefonopptak", "Opptak 231124"), and a loose match makes eight
#: real projects in the archive ambiguous. Tiering also settles the genuine cases:
#: KABB has both "Opptak" and "Opptak 231124", and only the former is a root.
#:
#: The second tier is the older convention. "orginalopptak" is not a typo here —
#: it is how the folder is actually spelled in two projects on disk.
FOOTAGE_ROOT_TIERS: tuple[frozenset[str], ...] = (
    frozenset({"opptak"}),
    frozenset({"originalopptak", "orginalopptak", "originaleopptak"}),
)

#: Legacy projects prefix top-level folders with an ordering number: "01 Opptak".
_NUMERIC_PREFIX = re.compile(r"^\d+[\s._-]+")
_SEPARATORS = re.compile(r"[\s._-]+")

#: Empty bins created at Master level alongside the footage tree.
EXTRA_BINS = ("Grafikk", "Musikk", "VOICE", "Timelines")

#: Extensions we import, lowercased. Split by kind only for readability — the
#: scanner treats them alike.
#:
#: Everything else is left alone on purpose. The archive's asset folders are full
#: of files Resolve cannot use as media: .drx grades, .pkf audio peaks, .xml and
#: .aaf round-trip files, .srt captions, .pdf and .eps artwork.
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".mxf", ".avi", ".mts", ".m4v", ".mpg", ".mpeg", ".vob", ".braw"}
)
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".aiff", ".aif", ".m4a", ".flac"})
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".arw", ".dng", ".cr2", ".nef", ".exr"}
)
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS

#: Folders never imported, at any depth. Normalised the same way as footage roots
#: (case, ordering-number prefix and separators ignored).
#:
#: Exports are excluded because they are renders of the very project being set up.
#: The rest hold no source media at all — caches, scratch files, Resolve's own
#: project and grade files, caption sidecars, and a discard folder.
EXCLUDED_FOLDERS = frozenset(
    {
        # Camera thumbnail folders inside the card structure (PRIVATE/M4ROOT/THMBNL,
        # private/XDROOT/Thmbnl). One ~50 KB JPEG per clip — 7,500 of them across the
        # reference archive, which is more images than every real stills folder
        # combined. Excluded rather than stripped: stripping would merge them into
        # the card's bin alongside the actual footage.
        "thmbnl",
        # Exports — including the two misspellings that exist on disk.
        "eksport",
        "eksporter",
        "eskport",
        "export",
        "exports",
        # Cache and scratch.
        "cache",
        "rendercache",
        "midlertidigefiler",
        "temp",
        "tmp",
        # Resolve's own files rather than media.
        "resolvefiler",
        "arkivertprosjektfil",
        "prosjektfil",
        # Caption sidecars — Resolve imports these outside the Media Pool.
        "subtitle",
        "subtitles",
        "srtsubtitle",
        "undertekster",
        # Discarded material.
        "slett",
    }
)

#: Directory names that are part of a camera's card structure rather than the
#: user's own organisation. Compared case-insensitively — a Sony FX3 writes
#: lowercase ``private`` while other bodies write ``PRIVATE``.
NOISE_SEGMENTS = frozenset(
    {
        "private",
        "m4root",
        "xdroot",
        "clip",
        "clpinf",
        "dcim",
        "avchd",
        "bdmv",
        "stream",
        "contents",
        "general",
        "misc",
    }
)
# "sub" is deliberately absent. Sony XDCAM writes low-resolution proxies to
# PRIVATE/XDROOT/Sub, so stripping it would merge proxies into the card's main bin
# — the opposite of how Proxy folders are handled. Left in place, it becomes its
# own sub-bin. No card in the reference archive uses it, so this is precautionary.

#: Numbered DCIM folders: 100MEDIA, 100GOPRO, 100EOS_R, 101MSDCF.
#:
#: The letter after the three digits is required. Without it the pattern also
#: matches bare year folders such as ``2024``/``2025``, which are meaningful
#: user organisation and were silently collapsing into a single bin.
DCIM_NUMBERED = re.compile(r"^\d{3}[a-z_][a-z0-9_]{0,5}$", re.IGNORECASE)


def _normalise_folder_name(name: str) -> str:
    """Casefold a folder name and drop its ordering-number prefix and separators."""
    return _SEPARATORS.sub("", _NUMERIC_PREFIX.sub("", name.strip())).casefold()


def is_excluded_folder(name: str) -> bool:
    """True if this top-level project folder should never be imported.

        >>> [is_excluded_folder(n) for n in ("Eksport", "09 EXPORT", "ESKPORT")]
        [True, True, True]
        >>> is_excluded_folder("Stills")
        False
    """
    return _normalise_folder_name(name) in EXCLUDED_FOLDERS


def footage_root_tier(name: str) -> int | None:
    """Priority of ``name`` as a footage-root folder, or None if it isn't one.

    Lower is better. Ignores case, an ordering-number prefix, and separators:

        >>> footage_root_tier("Opptak"), footage_root_tier("01 OPPTAK")
        (0, 0)
        >>> footage_root_tier("01 ORGINALOPPTAK"), footage_root_tier("Originale opptak")
        (1, 1)
        >>> footage_root_tier("Mobilopptak") is None
        True
    """
    key = _normalise_folder_name(name)
    for tier, names in enumerate(FOOTAGE_ROOT_TIERS):
        if key in names:
            return tier
    return None


def is_noise_segment(segment: str) -> bool:
    """True if ``segment`` is camera card structure rather than a real bin name."""
    return segment.casefold() in NOISE_SEGMENTS or bool(DCIM_NUMBERED.match(segment))


def is_media_file(name: str) -> bool:
    """True if ``name`` is a media file we should import.

    Rejects AppleDouble sidecars (``._clip.mov``) and other dotfiles, which appear
    throughout footage copied to and from macOS volumes.
    """
    if name.startswith("."):
        return False
    return PurePath(name).suffix.casefold() in MEDIA_EXTENSIONS


def bin_path_for(relative_dir: PurePath | str) -> tuple[str, ...]:
    """Map a directory path (relative to the project root) to a Resolve bin path.

    Casing of the segments that survive is preserved as-is on disk.

        >>> bin_path_for("Opptak/Interview/FX3/private/M4ROOT/CLIP")
        ('Opptak', 'Interview', 'FX3')

    ``Proxy`` is deliberately not treated as noise, so camera-generated proxies
    land in their own sub-bin instead of mixing with the full-resolution clips.
    Both Sony proxy layouts therefore converge on the same bin, which is intended:

        >>> bin_path_for("Opptak/FX6/Kort 1/PRIVATE/XDROOT/Clip/Proxy")
        ('Opptak', 'FX6', 'Kort 1', 'Proxy')
    """
    parts = PurePath(relative_dir).parts
    return tuple(part for part in parts if not is_noise_segment(part))
