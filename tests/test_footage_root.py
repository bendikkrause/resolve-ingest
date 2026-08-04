"""Footage-root detection across the current and legacy folder conventions.

Every name here is one that actually occurs under /Volumes/Arkiv/Prosjekter.
"""

from __future__ import annotations

import pytest

from resolve_ingest.binmap import footage_root_tier
from resolve_ingest.scanner import (
    AmbiguousFootageRoot,
    FootageRootMissing,
    find_footage_root,
)


@pytest.mark.parametrize("name", ["Opptak", "opptak", "01 Opptak", "01 OPPTAK"])
def test_current_convention_is_top_tier(name):
    assert footage_root_tier(name) == 0


@pytest.mark.parametrize(
    "name",
    [
        "01 ORIGINALOPPTAK",
        "01 ORGINALOPPTAK",  # spelled this way on disk in two projects
        "Originale opptak",
        "ORIGINALE OPPTAK",
    ],
)
def test_legacy_convention_is_second_tier(name):
    assert footage_root_tier(name) == 1


@pytest.mark.parametrize(
    "name",
    [
        "Mobilopptak",
        "Droneopptak",
        "Telefonopptak",
        "Studioopptak",
        "GoPro opptak ",
        "Opptak 231124",
        "Opptak FX6",
        "Opptak Oslo 12-130326",
        "01 LYDOPPTAK",
        "Eksport",
        "Grafikk",
    ],
)
def test_lookalike_folders_are_not_footage_roots(name):
    """A substring search on "opptak" makes eight real projects ambiguous."""
    assert footage_root_tier(name) is None


def _project(tmp_path, *folders):
    for folder in folders:
        (tmp_path / folder).mkdir(parents=True)
    return tmp_path


def test_finds_current_convention(tmp_path):
    root = _project(tmp_path, "Opptak", "Eksport")
    assert find_footage_root(root).name == "Opptak"


def test_finds_legacy_convention(tmp_path):
    root = _project(tmp_path, "01 ORGINALOPPTAK", "02 Mediafiler", "03 Eksporter")
    assert find_footage_root(root).name == "01 ORGINALOPPTAK"


def test_current_convention_wins_over_legacy(tmp_path):
    root = _project(tmp_path, "Opptak", "01 ORIGINALOPPTAK")
    assert find_footage_root(root).name == "Opptak"


def test_plain_opptak_wins_over_lookalikes(tmp_path):
    """Real case: KABB has both 'Opptak' and 'Opptak 231124'."""
    root = _project(tmp_path, "Opptak", "Opptak 231124", "Mobilopptak")
    assert find_footage_root(root).name == "Opptak"


def test_two_equal_candidates_raise_rather_than_guess(tmp_path):
    root = _project(tmp_path, "01 ORIGINALOPPTAK", "Originale opptak")
    with pytest.raises(AmbiguousFootageRoot) as excinfo:
        find_footage_root(root)
    assert "01 ORIGINALOPPTAK" in str(excinfo.value)
    assert "Originale opptak" in str(excinfo.value)


def test_missing_footage_root_raises(tmp_path):
    root = _project(tmp_path, "Eksport", "Grafikk")
    with pytest.raises(FootageRootMissing):
        find_footage_root(root)


def test_override_by_name(tmp_path):
    root = _project(tmp_path, "Sarah&Shree", "Eksport")
    assert find_footage_root(root, "Sarah&Shree").name == "Sarah&Shree"


def test_override_by_absolute_path(tmp_path):
    root = _project(tmp_path, "Weird Folder")
    target = root / "Weird Folder"
    assert find_footage_root(root, target) == target


def test_override_wins_over_detection(tmp_path):
    root = _project(tmp_path, "Opptak", "Telefonopptak")
    assert find_footage_root(root, "Telefonopptak").name == "Telefonopptak"


def test_override_that_does_not_exist_raises(tmp_path):
    root = _project(tmp_path, "Opptak")
    with pytest.raises(FootageRootMissing):
        find_footage_root(root, "Nope")
