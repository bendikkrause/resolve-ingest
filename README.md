# Resolve Ingest

Point it at a project folder; get a DaVinci Resolve project with the bins already
built and every clip imported into the right one.

It mirrors how footage is organised on disk, minus the camera card structure —
`Opptak/Interview/FX3/private/M4ROOT/CLIP` becomes the bin `Opptak/Interview/FX3`.

No AI, no network, no API keys. It talks to Resolve through Blackmagic's own
scripting API.

## Download

Builds for macOS and Windows are attached to each
[release](https://github.com/bendikkrause/resolve-ingest/releases). Neither is
code-signed, so both operating systems warn on first launch — the release notes
give the exact steps.

The macOS build is **Apple Silicon only**; it will not start on an Intel Mac.

## Requirements

- **DaVinci Resolve Studio** with *Preferences → General → External scripting using* set to **Local**
- Resolve running when you create a project (previewing works without it)

## Usage

Double-click **Resolve Ingest.app**, choose the project folder, press **Preview** to
see the bin tree, then **Create project**.

The same binary is a CLI when given arguments:

```bash
"/Applications/Resolve Ingest.app/Contents/MacOS/Resolve Ingest" ~/Projects/MyFilm --dry-run
```

```bash
"/Applications/Resolve Ingest.app/Contents/MacOS/Resolve Ingest" ~/Projects/MyFilm --name "My Film" --fps 50
```

`--dry-run` never touches Resolve.

## Finding the footage

It looks for a folder directly inside the project root, in this order:

1. `Opptak` — also `01 Opptak`, `01 OPPTAK`
2. `01 ORIGINALOPPTAK`, `01 ORGINALOPPTAK`, `Originale opptak` — the older convention

Matching ignores case, a leading ordering number, and spacing. It is anchored, not
a substring search: `Mobilopptak`, `Droneopptak`, `Telefonopptak` and `Opptak 231124`
are *not* footage roots. Where a project has both `Opptak` and `Opptak 231124`, the
plain one wins.

If two folders score equally it stops and lists them rather than guessing. For
anything that follows neither convention, name the folder yourself:

```bash
"…/Resolve Ingest" ~/Projects/MyFilm --footage-root "Sarah&Shree"
```

The GUI has an optional **Footage folder** field for the same purpose.

## What it creates

- Project named after the root folder, 1920×1080 @ 25 fps by default
- The footage bin tree, mirroring the folders on disk with camera structure stripped.
  The top bin keeps the folder's real name — a legacy project gets a
  `01 ORGINALOPPTAK` bin, spelling included.
- **Every other project folder too** — `Stills`, `Musikk`, `Grafikk`, `Arkivbilder`,
  `Stock` and so on, with their subfolder structure. A folder with nothing
  importable in it still becomes an empty bin rather than disappearing.
- Empty bins: `Grafikk`, `Musikk`, `VOICE`, `Timelines` (merged with any real folder
  of the same name, case-insensitively — a `Voice` folder does not also produce a
  separate `VOICE` bin)

### What gets imported

| Kind | Extensions |
|---|---|
| Video | `.mp4` `.mov` `.mxf` `.avi` `.mts` `.m4v` `.mpg` `.mpeg` `.vob` `.braw` |
| Audio | `.wav` `.mp3` `.aiff` `.aif` `.m4a` `.flac` |
| Stills | `.jpg` `.jpeg` `.png` `.tif` `.tiff` `.arw` `.dng` `.cr2` `.nef` `.exr` |

Everything else is left alone — `.drx` grades, `.pkf` peak files, `.xml`/`.aaf`
round-trips, `.srt` captions, `.pdf`/`.eps` artwork.

Stills are imported one at a time. Handed a batch, Resolve merges consecutively
numbered images into a single image-sequence clip, which would turn a 188-photo
shoot into one clip. It costs about 32 ms per still against 3 ms batched, so a
project with a very large photo archive takes a while.

### What is never imported

At **any** depth: `Eksport` (and `Eksporter`, `09 EXPORT`, the `ESKPORT`
misspelling), `THMBNL`/`Thmbnl` camera thumbnail folders, caches and temp folders,
Resolve's own project/grade folders, subtitle folders, and `SLETT`. Hidden folders
such as `.blackmagicsync-v2` are skipped too.

`THMBNL` matters more than it sounds: it holds one thumbnail JPEG per clip, and
there are 7,500 of them in the reference archive — more images than every real
stills folder combined. They are excluded rather than stripped, because stripping
would merge them into the card's bin alongside the actual footage.

Footage is **linked in place** — nothing is copied or moved.

If a project of that name already exists it stops and tells you, rather than
modifying it.

## The path rules

Directory names that are camera card structure get dropped, case-insensitively:

```
private  m4root  xdroot  clip  clpinf  dcim
avchd    bdmv    stream  contents  sub  general  misc
```

…plus numbered DCIM folders like `100MEDIA`, `100GOPRO`, `100EOS_R`. The pattern
requires a letter after the three digits, so year folders such as `2024` survive.

Everything else is kept, including card folders (`Kort 1`) and camera names (`FX3`,
`A7IV`). `Proxy` and `Sub` are kept too, so camera proxies land in their own sub-bin
instead of mixing with the full-resolution clips.

One card's stills and video do share a bin: a Sony writes photos to
`DCIM/100MSDCF` and video to `PRIVATE/M4ROOT/CLIP`, and both are that card's
contents.

## Development

```bash
python3.12 -m venv .venv && .venv/bin/pip install pytest pyinstaller
```

```bash
.venv/bin/python -m pytest
```

The corpus tests need a real archive — a folder of project folders. Point them at
yours; without it they skip themselves:

```bash
RESOLVE_INGEST_ARCHIVE="/Volumes/YourDrive/Prosjekter" .venv/bin/python -m pytest
```

`binmap.py` is pure — no Resolve import — so the rules are tested without Resolve
running. `tests/test_corpus.py` runs the scanner across a real footage archive and
asserts that no camera structure leaks into bin names, that no project is ambiguous,
and that no two source directories silently merge into one bin (except proxies,
which merge by design). It skips itself when the archive volume isn't mounted.

Build the app:

```bash
.venv/bin/pyinstaller packaging/resolve-ingest.spec --noconfirm
```

### Windows build

PyInstaller cannot cross-compile, so the Windows executable is built on a hosted
Windows runner by `.github/workflows/build-windows.yml`.

Ready-made builds are attached to each
[release](https://github.com/bendikkrause/resolve-ingest/releases) — those need no
GitHub account. Every push also produces a `Resolve-Ingest-Windows` artifact under
the **Actions** tab, but downloading an artifact requires being signed in.

Either way you get two files:

- `Resolve Ingest.exe` — the app
- `Resolve Ingest (console).exe` — identical, but keeps a console window so the
  CLI is usable and errors are readable

The build is unsigned, so Windows SmartScreen shows a warning on first run
(**More info → Run anyway**).

## Status

macOS is built and tested end-to-end against a live Resolve Studio 21.

Windows builds and the full test suite passes there, but the app has **not yet been
run against a real Resolve install on Windows**. The scripting paths in
`resolve_api.py` match Blackmagic's documented layout exactly, so the likely
failure mode is none at all — but if Resolve isn't found, that is where to look.
Use the console build to see the error.

The app is unsigned — macOS Gatekeeper will warn on first launch on another
machine. Distribution needs signing and notarisation.

Of 77 folders in the reference archive, 35 are recognised project roots. The rest
are client grouping folders (point one level deeper) or projects with no footage
folder at all.
