"""Golden cases for the path -> bin mapping.

Every path in ``REAL_TRANSFORMS`` was taken from the actual footage archive at
/Volumes/Arkiv/Prosjekter (32,315 media files across 58 projects), not
invented. If a rule change breaks one of these, it breaks real projects.
"""

from __future__ import annotations

import pytest

from resolve_ingest.binmap import bin_path_for, is_media_file, is_noise_segment

# (path relative to project root, expected bin path)
REAL_TRANSFORMS = [
    # Sony FX3 writes 'private' in lowercase; other bodies write 'PRIVATE'.
    (
        "Opptak/Bjørn Åsheim 050326/FX3/private/M4ROOT/CLIP",
        ("Opptak", "Bjørn Åsheim 050326", "FX3"),
    ),
    (
        "Opptak/050526/FX3/private/M4ROOT/CLIP",
        ("Opptak", "050526", "FX3"),
    ),
    (
        "Opptak/FX3/M4ROOT/CLIP",
        ("Opptak", "FX3"),
    ),
    # DCIM-based cameras.
    (
        "Opptak/Testopptak 040922/A2S/DCIM/100MEDIA",
        ("Opptak", "Testopptak 040922", "A2S"),
    ),
    ("Opptak/Canon EOS R/DCIM/100EOS_R", ("Opptak", "Canon EOS R")),
    ("Opptak/Feltopptak Gopro 12/DCIM/100GOPRO", ("Opptak", "Feltopptak Gopro 12")),
    # Already-flat layouts (archive footage, drone, some camera dumps) pass through.
    ("Opptak/Arkivklipp 120326", ("Opptak", "Arkivklipp 120326")),
    ("Opptak/Testopptak 040922/A7IV", ("Opptak", "Testopptak 040922", "A7IV")),
    (
        "Opptak/Lillevik - Erling 200526/M4ROOT/CLIP",
        ("Opptak", "Lillevik - Erling 200526"),
    ),
]


@pytest.mark.parametrize("source,expected", REAL_TRANSFORMS)
def test_real_archive_transforms(source, expected):
    assert bin_path_for(source) == expected


def test_card_folders_are_preserved():
    """'Kort N' is Norwegian for 'card N' and appears across 14+ real projects.

    These are meaningful user organisation, not camera structure.
    """
    assert bin_path_for("Opptak/FX6/Kort 1/PRIVATE/M4ROOT/CLIP") == (
        "Opptak",
        "FX6",
        "Kort 1",
    )
    assert bin_path_for("Opptak/Shoot/Kort 3") == ("Opptak", "Shoot", "Kort 3")


@pytest.mark.parametrize("year", ["2024", "2025", "1999"])
def test_year_folders_survive(year):
    """Regression: a DCIM pattern of ^\\d{3}[a-z0-9_]{1,6}$ also matches '2024'.

    That silently merged Opptak/Domkirken/2024 and /2025 into one bin.
    """
    assert bin_path_for(f"Opptak/Domkirken/{year}") == (
        "Opptak",
        "Domkirken",
        year,
    )


def test_both_sony_proxy_layouts_converge_on_one_proxy_bin():
    """Intended merge: proxies get their own sub-bin regardless of card layout."""
    expected = ("Opptak", "FX6", "Kort 1", "Proxy")
    assert bin_path_for("Opptak/FX6/Kort 1/PRIVATE/M4ROOT/CLIP/Proxy") == expected
    assert bin_path_for("Opptak/FX6/Kort 1/PRIVATE/XDROOT/Clip/Proxy") == expected


@pytest.mark.parametrize(
    "segment", ["PRIVATE", "private", "Private", "M4ROOT", "XDROOT", "CLIP", "Clip", "DCIM"]
)
def test_noise_matching_is_case_insensitive(segment):
    assert is_noise_segment(segment)


@pytest.mark.parametrize("segment", ["100MEDIA", "100GOPRO", "100EOS_R", "101MSDCF"])
def test_numbered_dcim_folders_are_noise(segment):
    assert is_noise_segment(segment)


@pytest.mark.parametrize("segment", ["Kort 1", "FX3", "Proxy", "2024", "A7IV", "Drone"])
def test_meaningful_segments_are_not_noise(segment):
    assert not is_noise_segment(segment)


@pytest.mark.parametrize(
    "name",
    [
        "A001.MP4",
        "clip.mov",
        "C0001.mp4",
        "shot.MOV",
        "broll.mxf",  # Canon/Panasonic, and archive footage
        "old.avi",
        "track.wav",  # Musikk folders are mostly .wav
        "sting.mp3",
        "vo.aiff",
        "still.jpg",  # Stills / Stillbilder / Arkivbilder
        "logo.png",
        "scan.tif",
        "photo.ARW",  # Sony raw stills, alongside video on the same card
    ],
)
def test_media_files_recognised(name):
    assert is_media_file(name)


@pytest.mark.parametrize(
    "name",
    [
        "._C0001.mp4",  # AppleDouble sidecar
        ".DS_Store",
        "notes.txt",
        "grade.drx",  # DaVinci grade, found in Grafikk folders
        "audio.pkf",  # Premiere peak file, found beside .wav
        "captions.srt",
        "roundtrip.xml",
        "artwork.eps",
        "brief.pdf",
    ],
)
def test_non_media_and_sidecars_rejected(name):
    assert not is_media_file(name)


def test_root_level_media_maps_to_footage_root():
    assert bin_path_for("Opptak") == ("Opptak",)
