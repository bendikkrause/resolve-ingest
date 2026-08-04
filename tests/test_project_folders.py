"""Scanning the whole project root, not just the footage folder.

Asset folders alongside the footage — Stills, Musikk, Arkivbilder — become bins too.
Exports and a handful of non-media folders are always skipped.
"""

from __future__ import annotations

import pytest

from resolve_ingest.binmap import is_excluded_folder
from resolve_ingest.scanner import scan


@pytest.mark.parametrize(
    "name",
    [
        "Eksport",
        "eksport",
        "Eksporter",
        "09 EXPORT",
        "03 Eksporter",
        "ESKPORT",  # misspelled on disk in one project
        "Eskport",
        "06 CACHE",
        "Midlertidige filer",
        "Resolve Filer",
        "00 ARKIVERT PROSJEKTFIL",
        "Subtitle",
        "Subtitles",
        "SRT subtitle",
        "SLETT",
    ],
)
def test_excluded_folders(name):
    assert is_excluded_folder(name)


@pytest.mark.parametrize(
    "name",
    [
        "Opptak",
        "Stills",
        "Stillbilder",
        "Grafikk",
        "Musikk",
        "Lydeffekter",
        "Arkivbilder",
        "Arkivfilm",
        "SFX",
        "Voice",
        "Behind the scenes",
        "Stock",
    ],
)
def test_asset_folders_are_kept(name):
    assert not is_excluded_folder(name)


def _project(tmp_path, files: dict[str, str]):
    """Build a fake project; keys are relative paths, values are file names."""
    for folder, filename in files.items():
        d = tmp_path / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_bytes(b"")
    return tmp_path


def test_asset_folders_become_bins(tmp_path):
    root = _project(
        tmp_path,
        {
            "Opptak/Interview/FX3/private/M4ROOT/CLIP": "C0001.MP4",
            "Stills": "photo.jpg",
            "Musikk": "track.wav",
            "Arkivbilder": "old.tif",
        },
    )
    result = scan(root)
    assert ("Opptak", "Interview", "FX3") in result.bins
    assert ("Stills",) in result.bins
    assert ("Musikk",) in result.bins
    assert ("Arkivbilder",) in result.bins


def test_export_folder_is_never_imported(tmp_path):
    root = _project(
        tmp_path,
        {"Opptak/Shoot": "C0001.MP4", "Eksport": "final_cut.mov", "SLETT": "junk.mov"},
    )
    result = scan(root)
    assert ("Eksport",) not in result.bins
    assert ("SLETT",) not in result.bins
    assert set(result.excluded) == {"Eksport", "SLETT"}
    assert result.file_count == 1


def test_folder_without_importable_media_still_becomes_a_bin(tmp_path):
    root = _project(
        tmp_path, {"Opptak/Shoot": "C0001.MP4", "Grafikk": "logo.eps"}
    )
    result = scan(root)
    assert ("Grafikk",) not in result.bins  # nothing importable in it
    assert ("Grafikk",) in result.empty_bins


def test_hidden_folders_are_skipped(tmp_path):
    root = _project(
        tmp_path, {"Opptak/Shoot": "C0001.MP4", ".blackmagicsync-v2": "cached.mov"}
    )
    result = scan(root)
    assert result.file_count == 1
    assert not any(b[0].startswith(".") for b in result.bins)
    assert not any(b[0].startswith(".") for b in result.empty_bins)


def test_nested_asset_folders_keep_their_structure(tmp_path):
    root = _project(
        tmp_path,
        {
            "Opptak/Shoot": "C0001.MP4",
            "Grafikk/Logoer": "logo.png",
            "Grafikk/Lower thirds": "lt.mov",
        },
    )
    result = scan(root)
    assert ("Grafikk", "Logoer") in result.bins
    assert ("Grafikk", "Lower thirds") in result.bins


def test_camera_thumbnail_folders_are_excluded_at_any_depth(tmp_path):
    """THMBNL holds one ~50 KB JPEG per clip — 7,500 across the reference archive.

    They must be dropped, not stripped: stripping would merge them into the card's
    bin alongside the real footage.
    """
    root = _project(
        tmp_path,
        {
            "Opptak/Shoot/private/M4ROOT/CLIP": "C0001.MP4",
            "Opptak/Shoot/private/M4ROOT/THMBNL": "C0001T01.JPG",
            "Opptak/Other/private/XDROOT/Thmbnl": "396_9384T01.JPG",
        },
    )
    result = scan(root)
    assert result.file_count == 1
    assert not any("thmbnl" in seg.casefold() for b in result.bins for seg in b)


def test_a_user_folder_named_thumbnails_is_kept(tmp_path):
    """'Thumbnails' is someone's own folder; only the camera's 'THMBNL' is junk."""
    root = _project(
        tmp_path,
        {"Opptak/Shoot": "C0001.MP4", "Grafikk/Thumbnails": "cover.png"},
    )
    result = scan(root)
    assert ("Grafikk", "Thumbnails") in result.bins


def test_sony_sub_proxies_get_their_own_bin(tmp_path):
    """PRIVATE/XDROOT/Sub holds low-res proxies, so it must not merge with CLIP."""
    root = _project(
        tmp_path,
        {
            "Opptak/FX6/private/XDROOT/Clip": "C0001.MP4",
            "Opptak/FX6/private/XDROOT/Sub": "C0001S01.MP4",
        },
    )
    result = scan(root)
    assert ("Opptak", "FX6") in result.bins
    assert ("Opptak", "FX6", "Sub") in result.bins


def test_still_requires_a_footage_folder(tmp_path):
    """Without this guard, pointing at any folder would build a nonsense project."""
    from resolve_ingest.scanner import FootageRootMissing

    root = _project(tmp_path, {"Stills": "photo.jpg", "Musikk": "track.wav"})
    with pytest.raises(FootageRootMissing):
        scan(root)
