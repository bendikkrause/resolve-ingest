"""Import batching, tested against a stand-in Media Pool.

No Resolve needed — these assert the shape of the calls we make, which is exactly
where the image-sequence bug lived.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from resolve_ingest.builder import apply_working_folders, import_files


class FakeMediaPool:
    """Records ImportMedia calls and returns one item per path, as Resolve does."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def ImportMedia(self, paths):  # noqa: N802 - mirrors Resolve's API
        self.calls.append(list(paths))
        return [object() for _ in paths]


def test_video_and_audio_go_in_one_batch():
    pool = FakeMediaPool()
    files = [Path("/x/a.mp4"), Path("/x/b.mov"), Path("/x/c.wav")]
    import_files(pool, files)
    assert pool.calls == [["/x/a.mp4", "/x/b.mov", "/x/c.wav"]]


def test_stills_are_imported_one_at_a_time():
    """Batched, Resolve merges numbered stills into a single sequence clip."""
    pool = FakeMediaPool()
    files = [Path("/x/DSC_0001.jpg"), Path("/x/DSC_0002.jpg"), Path("/x/DSC_0003.jpg")]
    import_files(pool, files)
    assert pool.calls == [["/x/DSC_0001.jpg"], ["/x/DSC_0002.jpg"], ["/x/DSC_0003.jpg"]]


def test_mixed_folder_splits_batch_from_stills():
    pool = FakeMediaPool()
    files = [Path("/x/clip.mov"), Path("/x/DSC_0001.jpg"), Path("/x/DSC_0002.JPG")]
    import_files(pool, files)
    assert pool.calls == [["/x/clip.mov"], ["/x/DSC_0001.jpg"], ["/x/DSC_0002.JPG"]]


def test_every_file_is_accounted_for():
    pool = FakeMediaPool()
    files = [Path("/x/a.mp4"), Path("/x/b.jpg"), Path("/x/c.png"), Path("/x/d.wav")]
    imported = import_files(pool, files)
    assert len(imported) == len(files)
    assert sorted(p for call in pool.calls for p in call) == sorted(
        str(f) for f in files
    )


def test_empty_input_makes_no_calls():
    pool = FakeMediaPool()
    assert import_files(pool, []) == []
    assert pool.calls == []


class FakeProject:
    """Records SetSetting calls; returns True as Resolve does on success."""

    def __init__(self, reject: set[str] | None = None):
        self.settings: dict[str, str] = {}
        self.reject = reject or set()

    def SetSetting(self, key, value):  # noqa: N802 - mirrors Resolve's API
        if key in self.reject:
            return False
        self.settings[key] = value
        return True


def test_working_folders_point_at_the_project(tmp_path):
    project = FakeProject()
    apply_working_folders(project, tmp_path)
    assert project.settings["projectMediaLocation"] == str(tmp_path)
    assert project.settings["colorGalleryStillsLocation"] == str(tmp_path / ".gallery")


def test_cache_location_is_never_touched(tmp_path):
    """Cache is kept in one shared place on purpose, for easy cleanup."""
    project = FakeProject()
    apply_working_folders(project, tmp_path)
    assert "perfCacheClipsLocation" not in project.settings


def test_gallery_folder_is_created_and_hidden(tmp_path):
    """Hidden so a later scan never re-imports grade stills as source media."""
    apply_working_folders(FakeProject(), tmp_path)
    gallery = tmp_path / ".gallery"
    assert gallery.is_dir()
    assert gallery.name.startswith(".")


def test_existing_gallery_folder_is_reused(tmp_path):
    (tmp_path / ".gallery").mkdir()
    apply_working_folders(FakeProject(), tmp_path)  # must not raise
    assert (tmp_path / ".gallery").is_dir()


def test_rejected_settings_are_reported(tmp_path):
    project = FakeProject(reject={"projectMediaLocation"})
    lines: list[str] = []
    rejected = apply_working_folders(project, tmp_path, lines.append)
    assert rejected == ["projectMediaLocation"]
    assert any("rejected" in line for line in lines)


def test_grade_stills_in_the_gallery_are_not_rescanned(tmp_path):
    """End to end: the gallery folder must be invisible to a later scan."""
    from resolve_ingest.scanner import scan

    (tmp_path / "Opptak" / "Shoot").mkdir(parents=True)
    (tmp_path / "Opptak" / "Shoot" / "C0001.MP4").write_bytes(b"")
    apply_working_folders(FakeProject(), tmp_path)
    (tmp_path / ".gallery" / "grade_still.png").write_bytes(b"")

    result = scan(tmp_path)
    assert result.file_count == 1
    assert not any(".gallery" in seg for b in result.bins for seg in b)


class RecordingResolve:
    """A Resolve whose Project Manager only works once the UI is unblocked.

    Mirrors the real failure: while the Project Manager window is open, every
    ProjectManager method returns None.
    """

    def __init__(self, page=None):
        self.page = page
        self.order: list[str] = []

    def GetCurrentPage(self):  # noqa: N802
        return self.page

    def OpenPage(self, name):  # noqa: N802
        self.order.append("OpenPage")
        self.page = name
        return True

    def GetProjectManager(self):  # noqa: N802
        self.order.append("GetProjectManager")
        return _BlockablePM(self)


class _BlockablePM:
    def __init__(self, resolve):
        self.resolve = resolve

    def GetProjectListInCurrentFolder(self):  # noqa: N802
        return None if self.resolve.page is None else []

    def CreateProject(self, name):  # noqa: N802
        self.resolve.order.append("CreateProject")
        return None  # stop the build here; we only care about ordering


def test_build_clears_the_ui_block_before_creating(tmp_path):
    """The Project Manager window must be dismissed before CreateProject is tried."""
    from resolve_ingest.builder import BuildFailed, BuildOptions, build
    from resolve_ingest.scanner import ScanResult

    resolve = RecordingResolve(page=None)
    result = ScanResult(root=tmp_path, project_name="X")
    with pytest.raises(BuildFailed):
        build(result, BuildOptions(project_name="X"), resolve)

    assert resolve.order.index("OpenPage") < resolve.order.index("CreateProject")


def test_import_failure_returning_none_is_tolerated():
    """Resolve returns None rather than [] when an import fails outright."""

    class NullPool(FakeMediaPool):
        def ImportMedia(self, paths):  # noqa: N802
            self.calls.append(list(paths))
            return None

    pool = NullPool()
    assert import_files(pool, [Path("/x/a.mp4"), Path("/x/b.jpg")]) == []
    assert len(pool.calls) == 2
