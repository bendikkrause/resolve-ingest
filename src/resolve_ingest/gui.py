"""Tkinter front end.

Deliberately thin — every decision lives in :mod:`scanner` and :mod:`builder`, so
this module only moves values between widgets and those functions. That keeps the
option open of replacing it with Qt later without touching any logic.

The build runs on a worker thread (footage often lives on a network volume, and a
scan of a few thousand files is not instant). Tk is not thread-safe, so the worker
never touches widgets: it pushes lines onto a queue that the UI thread drains.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__
from .builder import BuildFailed, BuildOptions, ProjectExists, build
from .scanner import AmbiguousFootageRoot, FootageRootMissing, format_tree, scan

PAD = 10


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=PAD)
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(7, weight=1)

        self.root_var = tk.StringVar()
        self.name_var = tk.StringVar()
        self.footage_var = tk.StringVar()
        self.width_var = tk.StringVar(value="1920")
        self.height_var = tk.StringVar(value="1080")
        self.fps_var = tk.StringVar(value="25")
        self.status_var = tk.StringVar(value="Choose a project folder to begin.")

        self._messages: queue.Queue[str] = queue.Queue()
        self._busy = False

        self._build_widgets()
        self.after(100, self._drain)

    # ---------------------------------------------------------------- widgets

    def _build_widgets(self) -> None:
        row = 0
        ttk.Label(self, text="Project folder").grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(self, textvariable=self.root_var)
        entry.grid(row=row, column=1, sticky="ew", padx=(PAD, 4))
        ttk.Button(self, text="Browse…", command=self._choose_folder).grid(row=row, column=2)

        row += 1
        hint = "The folder containing “Opptak” or “01 ORIGINALOPPTAK”."
        ttk.Label(self, text=hint, foreground="grey").grid(
            row=row, column=1, sticky="w", padx=(PAD, 0), pady=(0, PAD)
        )

        row += 1
        ttk.Label(self, text="Project name").grid(row=row, column=0, sticky="w")
        ttk.Entry(self, textvariable=self.name_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", padx=(PAD, 0)
        )

        row += 1
        ttk.Label(self, text="Footage folder").grid(row=row, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(self, textvariable=self.footage_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", padx=(PAD, 0), pady=(4, 0)
        )

        row += 1
        ttk.Label(
            self,
            text="Optional — only if the footage folder is named something unusual.",
            foreground="grey",
        ).grid(row=row, column=1, sticky="w", padx=(PAD, 0))

        row += 1
        ttk.Label(self, text="Timeline").grid(row=row, column=0, sticky="w", pady=(PAD, 0))
        specs = ttk.Frame(self)
        specs.grid(row=row, column=1, columnspan=2, sticky="w", padx=(PAD, 0), pady=(PAD, 0))
        ttk.Entry(specs, textvariable=self.width_var, width=6).pack(side="left")
        ttk.Label(specs, text="×").pack(side="left", padx=4)
        ttk.Entry(specs, textvariable=self.height_var, width=6).pack(side="left")
        ttk.Label(specs, text="at").pack(side="left", padx=(PAD, 4))
        ttk.Entry(specs, textvariable=self.fps_var, width=5).pack(side="left")
        ttk.Label(specs, text="fps").pack(side="left", padx=4)

        row += 1
        actions = ttk.Frame(self)
        actions.grid(row=row, column=0, columnspan=3, sticky="ew", pady=PAD)
        self.preview_button = ttk.Button(actions, text="Preview", command=self._preview)
        self.preview_button.pack(side="left")
        self.create_button = ttk.Button(
            actions, text="Create project", command=self._create, default="active"
        )
        self.create_button.pack(side="left", padx=PAD)
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=120)

        row += 1
        ttk.Label(self, textvariable=self.status_var).grid(
            row=row, column=0, columnspan=3, sticky="w"
        )

        row += 1
        self.log = tk.Text(self, height=18, width=76, wrap="none", state="disabled")
        self.log.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        bar = ttk.Scrollbar(self, orient="vertical", command=self.log.yview)
        bar.grid(row=row, column=3, sticky="ns", pady=(4, 0))
        self.log.configure(yscrollcommand=bar.set)

    # ----------------------------------------------------------------- events

    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Select the project folder")
        if not chosen:
            return
        self.root_var.set(chosen)
        # Only prefill; never clobber a name the user has already typed.
        if not self.name_var.get().strip():
            self.name_var.set(Path(chosen).name)
        self._preview()

    def _preview(self) -> None:
        self._run(self._do_preview)

    def _create(self) -> None:
        self._run(self._do_create)

    # ----------------------------------------------------------- worker threads

    def _run(self, work) -> None:
        if self._busy:
            return
        root = self.root_var.get().strip()
        if not root:
            self.status_var.set("Choose a project folder first.")
            return

        self._busy = True
        self._clear_log()
        for button in (self.preview_button, self.create_button):
            button.state(["disabled"])
        self.progress.pack(side="left", padx=PAD)
        self.progress.start(12)

        def runner() -> None:
            try:
                work(Path(root))
            except Exception as exc:  # surfaced in the log rather than a traceback
                self._say(f"\nError: {exc}")
                self._messages.put("!status Failed.")
            finally:
                self._messages.put("!done")

        threading.Thread(target=runner, daemon=True).start()

    def _do_preview(self, root: Path) -> None:
        self._messages.put("!status Scanning…")
        try:
            result = scan(root, self.footage_var.get().strip() or None)
        except (FootageRootMissing, AmbiguousFootageRoot) as exc:
            self._say(str(exc))
            self._messages.put("!status No footage folder found.")
            return
        self._say(format_tree(result))
        self._messages.put(
            f"!status {result.file_count} clips in {result.bin_count} bins. "
            "Nothing has been created yet."
        )

    def _do_create(self, root: Path) -> None:
        # Imported here so the app still launches (and previews) without Resolve.
        from .resolve_api import (
            ResolveBusy,
            ResolveNotFound,
            ResolveNotRunning,
            connect,
            ensure_ui_ready,
        )

        # Reach Resolve before scanning. A project on a network volume takes a
        # minute to scan, and discovering Resolve was unreachable only afterwards
        # wastes all of it.
        self._messages.put("!status Connecting to DaVinci Resolve…")
        try:
            resolve = connect()
            if ensure_ui_ready(resolve):
                self._say("Dismissed Resolve's Project Manager window.")
        except (ResolveNotFound, ResolveNotRunning) as exc:
            self._say(str(exc))
            self._messages.put("!status Could not reach Resolve.")
            return
        except ResolveBusy as exc:
            self._say(str(exc))
            self._messages.put("!status Resolve is busy — nothing was changed.")
            return

        self._messages.put("!status Scanning…")
        try:
            result = scan(root, self.footage_var.get().strip() or None)
        except (FootageRootMissing, AmbiguousFootageRoot) as exc:
            self._say(str(exc))
            self._messages.put("!status No footage folder found.")
            return

        if not result.bins:
            self._say("No .mp4 or .mov files found.")
            self._messages.put("!status Nothing to import.")
            return

        try:
            width = int(self.width_var.get())
            height = int(self.height_var.get())
        except ValueError:
            self._say("Resolution must be whole numbers, e.g. 1920 × 1080.")
            self._messages.put("!status Invalid resolution.")
            return

        options = BuildOptions(
            project_name=self.name_var.get().strip() or result.project_name,
            width=width,
            height=height,
            fps=self.fps_var.get().strip() or "25",
        )

        try:
            summary = build(result, options, resolve, progress=self._say)
        except ProjectExists as exc:
            self._say(str(exc))
            self._messages.put("!status Project already exists — nothing was changed.")
            return
        except ResolveBusy as exc:
            self._say(str(exc))
            self._messages.put("!status Resolve is busy — nothing was changed.")
            return
        except BuildFailed as exc:
            self._say(str(exc))
            self._messages.put("!status Resolve refused the build.")
            return

        self._messages.put(
            f"!status Done — {summary.clips_imported} clips in "
            f"{summary.bins_created} bins."
        )

    # -------------------------------------------------------------- UI plumbing

    def _say(self, line: str) -> None:
        self._messages.put(line)

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _drain(self) -> None:
        """Pump worker messages into the widgets. Runs on the UI thread only."""
        try:
            while True:
                message = self._messages.get_nowait()
                if message == "!done":
                    self._busy = False
                    self.progress.stop()
                    self.progress.pack_forget()
                    for button in (self.preview_button, self.create_button):
                        button.state(["!disabled"])
                elif message.startswith("!status "):
                    self.status_var.set(message[len("!status ") :])
                else:
                    self.log.configure(state="normal")
                    self.log.insert("end", message + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain)


def main() -> int:
    root = tk.Tk()
    # Version in the title so a window left open from an older build is obvious —
    # a stale window silently running old code is hard to spot otherwise.
    root.title(f"Resolve Ingest {__version__}")
    root.minsize(720, 560)
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
