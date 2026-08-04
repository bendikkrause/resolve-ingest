"""Headless entry point. Also the harness used to validate scans against real archives."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import BuildFailed, BuildOptions, ProjectExists, build
from .scanner import AmbiguousFootageRoot, FootageRootMissing, format_tree, scan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resolve-ingest",
        description="Create a DaVinci Resolve project from a folder of footage.",
    )
    parser.add_argument("root", type=Path, help="Project root (the folder containing 'Opptak')")
    parser.add_argument(
        "-n", "--name", help="Project name (defaults to the root folder's name)"
    )
    parser.add_argument(
        "--footage-root",
        help=(
            "Folder holding the footage, if it is named something other than "
            "'Opptak' or '01 ORIGINALOPPTAK'. A name or an absolute path."
        ),
    )
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", default="25")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the bin tree that would be created and exit. Resolve is not touched.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    # Frozen builds block-buffer stdout when piped, so progress arrives in one lump
    # at the end and lands *after* any traceback on stderr — which makes a failure
    # look like it happened somewhere it didn't.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):  # not a real stream (e.g. under capture)
        pass

    try:
        result = scan(args.root, args.footage_root)
    except (FootageRootMissing, AmbiguousFootageRoot) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not result.bins:
        print(f"error: no .mp4 or .mov files found under {args.root}", file=sys.stderr)
        return 2

    print(format_tree(result))

    if args.dry_run:
        return 0

    options = BuildOptions(
        project_name=args.name or result.project_name,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )

    # Imported lazily so --dry-run works on machines without Resolve installed.
    from .resolve_api import ResolveBusy, ResolveNotFound, ResolveNotRunning, connect

    print()
    try:
        resolve = connect()
        summary = build(result, options, resolve, progress=print)
    except (
        ResolveNotFound,
        ResolveNotRunning,
        ResolveBusy,
        ProjectExists,
        BuildFailed,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print()
    print(
        f"Done — {summary.clips_imported} clips in {summary.bins_created} bins "
        f"in project {summary.project_name!r}."
    )
    for bin_path, wanted, got in summary.short_imports:
        print(f"  warning: {'/'.join(bin_path)} imported {got} of {wanted}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
