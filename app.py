# app.py (Deluxe GUI - fixed)
# Bug fix: implement _load_presets method so constructor call doesn't fall back to tkinter.__getattr__
# and raise AttributeError. This version adds _load_presets back into the FreePoopApp class.
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import os
from pathlib import Path
import json
import time
import sys

from ytpffmpeg_adaptor import YTPFFmpegAdaptor

# Optional modules
try:
    import plugin_manager as pm_mod
except Exception:
    pm_mod = None

try:
    import speech_to_text as stt_mod
except Exception:
    stt_mod = None

APP_TITLE = "FreePoop V2 - Deluxe (updated, fixed)"

class FreePoopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x760")
        self.adaptor = YTPFFmpegAdaptor()
        self.presets = {}
        # load presets before building UI so UI can reflect presets if needed
        self._load_presets()
        self.batch_jobs = []  # list of (out_path, preset_name)
        self._build_ui()

    # ----------------- Presets -----------------
    def _load_presets(self):
        """
        Load presets.json from the same directory as this script.
        If the file does not exist or fails to parse, fall back to builtin presets.
        """
        try:
            here = Path(__file__).resolve().parent
            presets_file = here / "presets.json"
            if presets_file.exists():
                with presets_file.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    self.presets = data.get("presets", {})
                    return
        except Exception as e:
            # Log to console; GUI log may not be available yet
            print(f"[FreePoopApp] warning loading presets.json: {e}", file=sys.stderr)

        # Fallback builtin presets
        self.presets = {
            "classic (2006-2009)": {
                "stutter": True, "stutter_ms": 120, "stutter_repeats": 6,
                "scramble": True, "scramble_segments": 8, "reverse": False,
                "pitch_semitones": 3
            },
            "early-era (2010-2014)": {
                "stutter": True, "stutter_ms": 120, "stutter_repeats": 6,
                "scramble": True, "scramble_segments": 8, "reverse": True,
                "pitch_semitones": -2
            },
            "mid-era (2015-2020)": {
                "stutter": False, "stutter_ms": 120, "stutter_repeats": 6,
                "scramble": True, "scramble_segments": 10, "reverse": False,
                "pitch_semitones": 0
            },
            "modern (2025)": {
                "stutter": True, "stutter_ms": 80, "stutter_repeats": 3,
                "scramble": False, "scramble_segments": 6, "reverse": True,
                "pitch_semitones": -5
            }
        }

    # ---------------- UI building ----------------
    def _build_ui(self):
        # Menu
        menubar = tk.Menu(self)
        projmenu = tk.Menu(menubar, tearoff=0)
        projmenu.add_command(label="New Project", command=self.new_project)
        projmenu.add_command(label="Save Project...", command=self.save_project)
        projmenu.add_command(label="Load Project...", command=self.load_project)
        menubar.add_cascade(label="Project", menu=projmenu)
        self.config(menu=menubar)

        toolbar = tk.Frame(self)
        toolbar.pack(side="top", fill="x", padx=8, pady=6)

        tk.Button(toolbar, text="Add Source", command=self.add_source).pack(side="left", padx=4)
        tk.Button(toolbar, text="Add Overlay", command=self.add_overlay).pack(side="left", padx=4)
        tk.Button(toolbar, text="Transcribe (STT)", command=self.transcribe_selected).pack(side="left", padx=4)
        tk.Button(toolbar, text="Export", command=self.export).pack(side="left", padx=4)
        tk.Button(toolbar, text="Batch Export...", command=self.batch_export_dialog).pack(side="left", padx=4)
        tk.Button(toolbar, text="Preview", command=self.preview).pack(side="left", padx=4)

        main_pane = tk.PanedWindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True, padx=8, pady=6)

        left_frame = tk.Frame(main_pane)
        main_pane.add(left_frame, width=380)
        right_frame = tk.Frame(main_pane)
        main_pane.add(right_frame)

        # Left column: sources/overlays/plugins
        tk.Label(left_frame, text="Sources", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.lst_sources = tk.Listbox(left_frame, width=60, height=8)
        self.lst_sources.pack(padx=4, pady=4)
        src_buttons = tk.Frame(left_frame)
        src_buttons.pack(fill="x", padx=4)
        tk.Button(src_buttons, text="Remove", command=self.remove_selected_source).pack(side="left", padx=2)

        tk.Label(left_frame, text="Overlays", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12,0))
        self.lst_overlays = tk.Listbox(left_frame, width=60, height=7)
        self.lst_overlays.pack(padx=4, pady=4)
        tk.Button(left_frame, text="Remove Overlay", command=self.remove_selected_overlay).pack(padx=4)

        # Right: effects and transcript / log
        eff_frame = tk.LabelFrame(right_frame, text="Effects & Export", padx=8, pady=8)
        eff_frame.pack(fill="x", padx=8, pady=(0,8))

        self.chk_stutter = tk.IntVar(value=1 if self.adaptor.effects.get("stutter") else 0)
        tk.Checkbutton(eff_frame, text="Stutter", variable=self.chk_stutter, command=self.update_effects).grid(row=0, column=0, sticky="w")
        tk.Label(eff_frame, text="ms").grid(row=0, column=2, sticky="w")
        self.ent_stutter_ms = tk.Spinbox(eff_frame, from_=20, to=2000, increment=10, width=6, command=self.update_effects)
        self.ent_stutter_ms.delete(0, "end")
        self.ent_stutter_ms.insert(0, str(self.adaptor.effects.get("stutter_ms", 120)))
        self.ent_stutter_ms.grid(row=0, column=1, sticky="w", padx=(6,12))

        self.chk_scramble = tk.IntVar(value=1 if self.adaptor.effects.get("scramble") else 0)
        tk.Checkbutton(eff_frame, text="Scramble", variable=self.chk_scramble, command=self.update_effects).grid(row=1, column=0, sticky="w")
        tk.Label(eff_frame, text="Segments").grid(row=1, column=2, sticky="w")
        self.ent_scramble_segments = tk.Spinbox(eff_frame, from_=2, to=64, width=6, command=self.update_effects)
        self.ent_scramble_segments.delete(0, "end")
        self.ent_scramble_segments.insert(0, str(self.adaptor.effects.get("scramble_segments", 8)))
        self.ent_scramble_segments.grid(row=1, column=1, sticky="w", padx=(6,12))

        self.chk_reverse = tk.IntVar(value=1 if self.adaptor.effects.get("reverse") else 0)
        tk.Checkbutton(eff_frame, text="Reverse", variable=self.chk_reverse, command=self.update_effects).grid(row=2, column=0, sticky="w")

        tk.Label(eff_frame, text="Pitch (semitones)").grid(row=3, column=0, sticky="w", pady=(8,0))
        self.sld_pitch = tk.Scale(eff_frame, from_=-12, to=12, orient="horizontal", length=260, command=self.update_pitch)
        self.sld_pitch.set(self.adaptor.effects.get("pitch_semitones", 0.0))
        self.sld_pitch.grid(row=4, column=0, columnspan=3, sticky="w")

        # Chroma key
        chroma_frame = tk.LabelFrame(right_frame, text="Chroma Key (Green Screen)", padx=8, pady=8)
        chroma_frame.pack(fill="x", padx=8, pady=(0,8))
        self.chk_chroma = tk.IntVar(value=0)
        tk.Checkbutton(chroma_frame, text="Enable Chroma Key", variable=self.chk_chroma, command=self.update_chroma).grid(row=0, column=0, sticky="w")
        tk.Label(chroma_frame, text="Similarity").grid(row=0, column=1, sticky="w")
        self.sld_chroma_sim = tk.Scale(chroma_frame, from_=0.01, to=0.8, resolution=0.01, orient="horizontal", length=220)
        self.sld_chroma_sim.set(0.2)
        self.sld_chroma_sim.grid(row=0, column=2, padx=6)
        tk.Label(chroma_frame, text="Blend").grid(row=1, column=1, sticky="w")
        self.sld_chroma_blend = tk.Scale(chroma_frame, from_=0, to=1.0, resolution=0.01, orient="horizontal", length=220)
        self.sld_chroma_blend.set(0.1)
        self.sld_chroma_blend.grid(row=1, column=2, padx=6)

        # Vocoder/Plugins
        plugin_frame = tk.LabelFrame(right_frame, text="Plugins / Vocoder", padx=8, pady=8)
        plugin_frame.pack(fill="x", padx=8, pady=(0,8))
        self.chk_vocoder = tk.IntVar(value=0)
        tk.Checkbutton(plugin_frame, text="Use vocoder plugin (if enabled)", variable=self.chk_vocoder).pack(anchor="w")
        tk.Button(plugin_frame, text="Refresh Plugins", command=self.refresh_plugins).pack(anchor="w", pady=(4,0))

        # Transcript & Poopify Editor
        trans_frame = tk.LabelFrame(right_frame, text="Transcript & Poopify", padx=8, pady=8)
        trans_frame.pack(fill="both", expand=True, padx=8, pady=(0,8))

        self.txt_original = tk.Text(trans_frame, height=10)
        self.txt_original.pack(fill="both", expand=True)
        poop_opts = tk.Frame(trans_frame)
        poop_opts.pack(fill="x", pady=(6,0))
        tk.Button(poop_opts, text="Poopify -> Preview", command=self.poopify_transcript).pack(side="left")
        self.sld_shuffle = tk.Scale(poop_opts, from_=0.0, to=1.0, resolution=0.05, orient="horizontal", length=240)
        self.sld_shuffle.set(0.45)
        self.sld_shuffle.pack(side="left", padx=8)

        # Bottom log and batch jobs
        bottom = tk.LabelFrame(self, text="Log / Batch Jobs", padx=8, pady=8)
        bottom.pack(fill="both", padx=8, pady=(0,8), expand=False)
        self.txt_log = tk.Text(bottom, height=10)
        self.txt_log.pack(fill="both", expand=True)

        # initial plugin refresh
        self.refresh_plugins()

    # ---------------- Project ----------------
    def new_project(self):
        self.adaptor = YTPFFmpegAdaptor()
        self.lst_sources.delete(0, "end")
        self.lst_overlays.delete(0, "end")
        self.txt_log.delete("1.0", "end")
        self.log("New project created.")

    def save_project(self):
        if not self.adaptor.sources and not self.adaptor.overlays:
            messagebox.showwarning("Empty project", "No sources or overlays to save.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("FreePoop project", "*.json")])
        if not path:
            return
        data = self.adaptor.export_project_state()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        self.log(f"Project saved: {path}")

    def load_project(self):
        path = filedialog.askopenfilename(title="Open project", filetypes=[("FreePoop project", "*.json")])
        if not path:
            return
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.adaptor.load_project_state(data)
        # refresh UI lists
        self.lst_sources.delete(0, "end")
        for s in self.adaptor.sources:
            self.lst_sources.insert("end", str(s))
        self.lst_overlays.delete(0, "end")
        for ov in self.adaptor.overlays:
            self.lst_overlays.insert("end", str(ov.get("path")))
        self.log(f"Project loaded: {path}")

    # ---------------- Sources / Overlays ----------------
    def add_source(self):
        fn = filedialog.askopenfilename(title="Select source video/audio")
        if not fn:
            return
        try:
            p = self.adaptor.add_source(fn)
            self.lst_sources.insert("end", str(p))
            self.log(f"Added source: {p}")
        except Exception as e:
            messagebox.showerror("Add source error", str(e))
            self.log("Add source error: " + str(e))

    def remove_selected_source(self):
        sel = self.lst_sources.curselection()
        if not sel:
            return
        idx = sel[0]
        p = self.lst_sources.get(idx)
        self.lst_sources.delete(idx)
        self.adaptor.sources = [s for s in self.adaptor.sources if str(s) != p]
        self.log(f"Removed source: {p}")

    def add_overlay(self):
        fn = filedialog.askopenfilename(title="Select overlay (image/gif/video)")
        if not fn:
            return
        # If GIF, offer loop/fps dialog
        if fn.lower().endswith(".gif"):
            dlg = tk.Toplevel(self)
            dlg.title("GIF Overlay Options")
            tk.Label(dlg, text="Loop count (0=infinite, 1=single)").pack(padx=8, pady=6)
            spin_loop = tk.Spinbox(dlg, from_=0, to=10, width=6)
            spin_loop.delete(0, "end"); spin_loop.insert(0, "0"); spin_loop.pack(padx=8)
            tk.Label(dlg, text="FPS (output)").pack(padx=8, pady=(6,0))
            spin_fps = tk.Spinbox(dlg, from_=6, to=60, width=6)
            spin_fps.delete(0, "end"); spin_fps.insert(0, "15"); spin_fps.pack(padx=8)
            def on_ok():
                loop = int(spin_loop.get())
                fps = int(spin_fps.get())
                try:
                    conv = self.adaptor.prepare_overlay_from_gif(fn, loop=loop, fps=fps)
                    self.adaptor.add_overlay(str(conv))
                    self.lst_overlays.insert("end", f"{conv} (converted gif)")
                    self.log(f"Added overlay (converted gif): {conv}")
                except Exception as e:
                    messagebox.showerror("GIF convert error", str(e))
                    self.log("GIF convert error: " + str(e))
                dlg.destroy()
            tk.Button(dlg, text="OK", command=on_ok).pack(pady=8)
            return
        try:
            ov = self.adaptor.add_overlay(fn)
            self.lst_overlays.insert("end", str(ov.get("path")))
            self.log(f"Added overlay: {fn}")
        except Exception as e:
            messagebox.showerror("Add overlay error", str(e))
            self.log("Add overlay error: " + str(e))

    def remove_selected_overlay(self):
        sel = self.lst_overlays.curselection()
        if not sel:
            return
        idx = sel[0]
        p = self.lst_overlays.get(idx)
        self.lst_overlays.delete(idx)
        self.adaptor.overlays = [o for o in self.adaptor.overlays if str(o.get("path")) != p]
        self.log(f"Removed overlay: {p}")

    # ---------------- Plugins ----------------
    def refresh_plugins(self):
        if self.adaptor.plugin_manager is None:
            self.log("No plugin manager available.")
            return
        self.adaptor.plugin_manager.discover()
        self.log("Plugins refreshed.")

    # ---------------- Effects ----------------
    def update_effects(self):
        try:
            st_ms = int(self.ent_stutter_ms.get())
        except Exception:
            st_ms = 120
        try:
            scr_seg = int(self.ent_scramble_segments.get())
        except Exception:
            scr_seg = 8
        self.adaptor.set_effect("stutter", bool(self.chk_stutter.get()))
        self.adaptor.set_effect("stutter_ms", st_ms)
        self.adaptor.set_effect("stutter_repeats", int(self.adaptor.effects.get("stutter_repeats", 6)))
        self.adaptor.set_effect("scramble", bool(self.chk_scramble.get()))
        self.adaptor.set_effect("scramble_segments", scr_seg)
        self.adaptor.set_effect("reverse", bool(self.chk_reverse.get()))
        # chroma
        self.adaptor.set_effect("chroma_enabled", bool(self.chk_chroma.get()))
        self.adaptor.set_effect("chroma_similarity", float(self.sld_chroma_sim.get()))
        self.adaptor.set_effect("chroma_blend", float(self.sld_chroma_blend.get()))
        self.log("Effects updated.")

    def update_pitch(self, val):
        v = float(val)
        self.adaptor.set_effect("pitch_semitones", v)
        self.log(f"Pitch set to {v}")

    def update_chroma(self):
        self.update_effects()

    # ---------------- Transcription / Poopify ----------------
    def transcribe_selected(self):
        if not self.adaptor.sources:
            messagebox.showwarning("No source", "Please add a source to transcribe.")
            return
        if stt_mod is None or not hasattr(stt_mod, "transcribe_file"):
            messagebox.showinfo("STT not available", "STT backend not installed. Install faster-whisper/whisper or speech_recognition.")
            return
        src = str(self.adaptor.sources[0])
        def do_transcribe():
            self.log("Transcribing...")
            try:
                txt = stt_mod.transcribe_file(src)
                self.txt_original.delete("1.0", "end")
                self.txt_original.insert("1.0", txt)
                self.log("Transcription complete.")
            except Exception as e:
                self.log("STT error: " + str(e))
                messagebox.showerror("STT error", str(e))
        threading.Thread(target=do_transcribe, daemon=True).start()

    def poopify_transcript(self):
        src_txt = self.txt_original.get("1.0", "end").strip()
        if not src_txt:
            messagebox.showwarning("No transcript", "Transcribe or paste transcript first.")
            return
        intensity = float(self.sld_shuffle.get())
        pooped = self.simple_pooper(src_txt, intensity)
        # show pooped inline
        self.txt_original.delete("1.0", "end")
        self.txt_original.insert("1.0", pooped)
        # store to adaptor preset params
        self.adaptor.preset_params["pooped_transcript"] = pooped
        self.log("Poopified transcript stored in project state.")

    def simple_pooper(self, text, intensity=0.5):
        import random
        random.seed(int(time.time()) & 0xFFFF)
        words = text.split()
        n = len(words)
        if n <= 1:
            return text
        swaps = max(1, int(n * intensity * 0.5))
        for _ in range(swaps):
            i = random.randrange(n)
            j = random.randrange(n)
            words[i], words[j] = words[j], words[i]
        return " ".join(words)

    # ---------------- Export / Batch ----------------
    def preview(self):
        try:
            self.adaptor.preview()
            self.log("Preview started.")
        except Exception as e:
            self.log("Preview error: " + str(e))
            messagebox.showerror("Preview error", str(e))

    def export(self):
        if not self.adaptor.sources:
            messagebox.showwarning("No source", "Add a source before exporting.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
        if not out:
            return
        # update effects
        self.update_effects()
        # allow vocoder plugin usage (plugin logic handled in adaptor/plugin manager)
        def run_export(outp):
            self.log(f"Export started: {outp}")
            proc = self.adaptor.export(outp)
            if proc.returncode == 0:
                self.log(f"Export succeeded: {outp}")
            else:
                self.log(f"Export failed: {outp}\n{proc.stderr}")
        threading.Thread(target=run_export, args=(out,), daemon=True).start()

    def batch_export_dialog(self):
        if not self.adaptor.sources:
            messagebox.showwarning("No source", "Add at least one source before batch exporting.")
            return
        folder = filedialog.askdirectory(title="Select output folder for batch exports")
        if not folder:
            return
        dlg = tk.Toplevel(self)
        dlg.title("Batch export settings")
        tk.Label(dlg, text="Number of outputs").pack(padx=8, pady=6)
        spin = tk.Spinbox(dlg, from_=1, to=64, width=6); spin.delete(0, "end"); spin.insert(0, "3"); spin.pack(padx=8)
        def on_ok():
            n = int(spin.get())
            for i in range(n):
                outp = Path(folder) / f"freepoop_batch_{i+1}.mp4"
                import random
                pitch = (i - n//2) * 0.5
                self.adaptor.set_effect("pitch_semitones", pitch)
                t = threading.Thread(target=self._batch_export_run, args=(str(outp),), daemon=True)
                t.start()
            dlg.destroy()
        tk.Button(dlg, text="Start", command=on_ok).pack(pady=8)

    def _batch_export_run(self, outp):
        self.log(f"Batch job started: {outp}")
        proc = self.adaptor.export(outp)
        if proc.returncode == 0:
            self.log(f"Batch job finished: {outp}")
        else:
            self.log(f"Batch job failed: {outp}\n{proc.stderr}")

    # ---------------- Utilities ----------------
    def log(self, text: str):
        ts = time.strftime("%H:%M:%S")
        try:
            self.txt_log.insert("end", f"[{ts}] {text}\n")
            self.txt_log.see("end")
        except Exception:
            # if log widget not yet ready, print to stderr
            print(f"[{ts}] {text}", file=sys.stderr)

if __name__ == "__main__":
    app = FreePoopApp()
    app.mainloop()