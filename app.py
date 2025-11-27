# app.py
# Simple Tkinter GUI frontend for the YTPFFmpegAdaptor.
# This is a minimal starter UI for adding sources/overlays, toggling effects, selecting presets, preview and export.
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import os
from pathlib import Path
import json

from ytpffmpeg_adaptor import YTPFFmpegAdaptor

APP_TITLE = "FreePoop V2 - YTP Generator (starter GUI)"

class FreePoopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("800x520")
        self.adaptor = YTPFFmpegAdaptor()
        self._build_ui()
        self.presets = {}
        self._load_presets()

    def _build_ui(self):
        frm_left = tk.Frame(self)
        frm_left.pack(side="left", fill="y", padx=8, pady=8)

        tk.Label(frm_left, text="Sources").pack(anchor="w")
        self.lst_sources = tk.Listbox(frm_left, width=40, height=8)
        self.lst_sources.pack()
        tk.Button(frm_left, text="Add Source", command=self.add_source).pack(fill="x", pady=(4,0))
        tk.Button(frm_left, text="Preview Source", command=self.preview).pack(fill="x", pady=(2,6))

        tk.Label(frm_left, text="Overlays").pack(anchor="w")
        self.lst_overlays = tk.Listbox(frm_left, width=40, height=6)
        self.lst_overlays.pack()
        tk.Button(frm_left, text="Add Overlay", command=self.add_overlay).pack(fill="x", pady=(4,0))

        frm_right = tk.Frame(self)
        frm_right.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        tk.Label(frm_right, text="Effects & Presets").pack(anchor="w")
        self.chk_stutter = tk.IntVar()
        tk.Checkbutton(frm_right, text="Stutter", variable=self.chk_stutter, command=self.update_effects).pack(anchor="w")
        self.chk_scramble = tk.IntVar()
        tk.Checkbutton(frm_right, text="Scramble", variable=self.chk_scramble, command=self.update_effects).pack(anchor="w")
        self.chk_reverse = tk.IntVar()
        tk.Checkbutton(frm_right, text="Reverse", variable=self.chk_reverse, command=self.update_effects).pack(anchor="w")

        tk.Label(frm_right, text="Pitch shift (semitones)").pack(anchor="w", pady=(8,0))
        self.sld_pitch = tk.Scale(frm_right, from_=-12, to=12, orient="horizontal", command=self.update_pitch)
        self.sld_pitch.set(0)
        self.sld_pitch.pack(fill="x")

        tk.Label(frm_right, text="Preset").pack(anchor="w", pady=(8,0))
        self.cmb_preset = ttk.Combobox(frm_right, state="readonly")
        self.cmb_preset.pack(fill="x")
        self.cmb_preset.bind("<<ComboboxSelected>>", self.preset_selected)

        frm_actions = tk.Frame(frm_right)
        frm_actions.pack(fill="x", pady=(12,0))
        tk.Button(frm_actions, text="Export", command=self.export).pack(side="left", padx=4)
        tk.Button(frm_actions, text="Quit", command=self.quit).pack(side="left", padx=4)

        self.txt_log = tk.Text(self, height=8)
        self.txt_log.pack(fill="x", padx=8, pady=8)

    def add_source(self):
        fn = filedialog.askopenfilename(title="Select source video/audio")
        if not fn:
            return
        path = Path(fn)
        try:
            self.adaptor.add_source(str(path))
            self.lst_sources.insert("end", str(path))
            self.log(f"Added source: {path}")
        except Exception as e:
            messagebox.showerror("Error adding source", str(e))

    def add_overlay(self):
        fn = filedialog.askopenfilename(title="Select overlay (image/gif)")
        if not fn:
            return
        try:
            ov = self.adaptor.add_overlay(fn)
            self.lst_overlays.insert("end", f"{fn}")
            self.log(f"Added overlay: {fn}")
        except Exception as e:
            messagebox.showerror("Error adding overlay", str(e))

    def update_effects(self):
        self.adaptor.set_effect("stutter", bool(self.chk_stutter.get()))
        self.adaptor.set_effect("scramble", bool(self.chk_scramble.get()))
        self.adaptor.set_effect("reverse", bool(self.chk_reverse.get()))
        self.log("Effects updated")

    def update_pitch(self, val):
        v = float(val)
        self.adaptor.set_effect("pitch_semitones", v)
        self.log(f"Pitch set to {v} semitones")

    def _load_presets(self):
        try:
            here = Path(__file__).parent
            presets_file = here / "presets.json"
            if presets_file.exists():
                with open(presets_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    self.presets = data.get("presets", {})
                    keys = list(self.presets.keys())
                    self.cmb_preset['values'] = keys
                    if keys:
                        self.cmb_preset.current(0)
        except Exception as e:
            self.log("Warning loading presets: " + str(e))

    def preset_selected(self, _evt):
        key = self.cmb_preset.get()
        preset = self.presets.get(key)
        if preset:
            self.adaptor.load_preset(preset)
            # update UI
            self.chk_stutter.set(1 if preset.get("stutter") else 0)
            self.chk_scramble.set(1 if preset.get("scramble") else 0)
            self.chk_reverse.set(1 if preset.get("reverse") else 0)
            self.sld_pitch.set(preset.get("pitch_semitones", 0))
            self.log(f"Preset loaded: {key}")

    def preview(self):
        try:
            self.adaptor.preview()
        except Exception as e:
            messagebox.showerror("Preview error", str(e))

    def export(self):
        if not self.adaptor.sources:
            messagebox.showwarning("No source", "Please add a source before exporting.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")], title="Export to")
        if not out:
            return
        # Run export in background thread to avoid freezing GUI
        def do_export():
            self.log("Starting export...")
            try:
                proc = self.adaptor.export(out)
                if proc.returncode == 0:
                    self.log("Export finished successfully: " + out)
                    messagebox.showinfo("Export complete", "Export finished successfully.")
                else:
                    self.log("Export failed. ffmpeg stderr follows:")
                    self.log(proc.stderr)
                    messagebox.showerror("Export failed", "See log for ffmpeg output.")
            except Exception as e:
                self.log("Export error: " + str(e))
                messagebox.showerror("Export error", str(e))

        t = threading.Thread(target=do_export, daemon=True)
        t.start()

    def log(self, text: str):
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")

if __name__ == "__main__":
    app = FreePoopApp()
    app.mainloop()