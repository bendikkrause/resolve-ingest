"""Regression tests against a real footage archive.

Point these at your own archive — a folder of project folders:

    RESOLVE_INGEST_ARCHIVE="/Volumes/YourDrive/Prosjekter" pytest

Skipped automatically when that path isn't there, so the suite still runs on a
laptop or a build machine.

These assert *invariants* rather than exact names or counts. Footage gets added
over time, and a test that fails because someone shot more material is a test
that gets ignored.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from resolve_ingest.binmap import footage_root_tier, is_noise_segment
from resolve_ingest.scanner import AmbiguousFootageRoot, FootageRootMissing, scan

ARCHIVE = Path(os.environ.get("RESOLVE_INGEST_ARCHIVE", "/Volumes/Arkiv/Prosjekter"))

pytestmark = pytest.mark.skipif(
    not ARCHIVE.is_dir(), reason=f"archive not mounted at {ARCHIVE}"
)


def _scan_all():
    results, ambiguous = [], []
    for project in sorted(p for p in ARCHIVE.iterdir() if p.is_dir()):
        try:
            results.append(scan(project))
        except FootageRootMissing:
            continue
        except AmbiguousFootageRoot as exc:
            ambiguous.append((project.name, [c.name for c in exc.candidates]))
    return results, ambiguous


@pytest.fixture(scope="module")
def scanned():
    results, ambiguous = _scan_all()
    assert results, "archive mounted but no project with a footage folder was found"
    return results, ambiguous


@pytest.fixture(scope="module")
def scans(scanned):
    return scanned[0]


def test_finds_the_expected_project_roots(scans):
    """35 project roots sat directly under Prosjekter when this was written.

    A floor rather than an equality: new projects should not fail the suite.
    """
    assert len(scans) >= 35


def test_no_project_is_ambiguous(scanned):
    """Footage-root detection must resolve every real project without guessing.

    A plain substring match on "opptak" makes eight of these ambiguous, which is
    why detection is tiered and anchored instead.
    """
    assert scanned[1] == []


def test_legacy_convention_projects_are_covered(scans):
    """The older '01 ORIGINALOPPTAK' layout must scan, not just the modern one.

    Identified by tier rather than by name, so this holds for any archive.
    """
    legacy = {
        r.project_name for r in scans for b in r.bins if b and footage_root_tier(b[0]) == 1
    }
    assert len(legacy) >= 3, f"expected legacy-convention projects, found {legacy}"


def test_no_camera_structure_leaks_into_bin_names(scans):
    """The whole point of the tool: PRIVATE/M4ROOT/CLIP must never become a bin."""
    leaked = [
        (r.project_name, "/".join(b))
        for r in scans
        for b in r.bins
        if any(is_noise_segment(seg) for seg in b)
    ]
    assert leaked == []


#: Every folder name the rules strip anywhere in the archive, all reviewed by hand
#: as genuine camera card structure. Deliberately an exhaustive list rather than a
#: count: it is the tripwire for a rule that starts eating meaningful folders.
REVIEWED_STRIPPED_SEGMENTS = {
    "private",
    "clip",
    "m4root",
    "xdroot",
    "dcim",
    "contents",
    "100eos_r",
    "100gopro",
    "100media",
    "100msdcf",
    "100olymp",
    "101olymp",
}


def test_only_reviewed_camera_structure_is_stripped(scans):
    """Nothing outside the reviewed vocabulary may be dropped from a bin path.

    This is the guard that catches a too-greedy rule. The earlier DCIM pattern
    also matched `2024`, and `2024` is not in this set.
    """
    stripped = {
        seg.casefold()
        for result in scans
        for files in result.bins.values()
        for f in files
        for seg in f.parent.relative_to(result.root).parts
        if is_noise_segment(seg)
    }
    assert stripped <= REVIEWED_STRIPPED_SEGMENTS


def test_stills_and_video_from_one_card_land_together(scans):
    """A Sony card writes stills to DCIM/100MSDCF and video to PRIVATE/M4ROOT/CLIP.

    Both are that card's contents, so they belong in one bin. This merge is the
    intended behaviour, not the data-mixing bug the test above guards against.
    """
    found = False
    for result in scans:
        for bin_path, files in result.bins.items():
            parents = {f.parent.relative_to(result.root).parts for f in files}
            if len(parents) < 2:
                continue
            flat = {seg.casefold() for parts in parents for seg in parts}
            if "dcim" in flat and "m4root" in flat:
                found = True
    assert found, "expected at least one card holding both stills and video"


def test_bins_are_never_empty(scans):
    """A bin in the result means media to put in it; empty ones are a scanner bug."""
    assert all(files for r in scans for files in r.bins.values())


def test_project_name_comes_from_the_root_folder(scans):
    assert all(r.project_name == r.root.name for r in scans)
