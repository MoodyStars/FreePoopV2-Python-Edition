# app.py
# Deluxe Tkinter GUI frontend for the enhanced YTPFFmpegAdaptor.
# Features added:
# - Robust controls for stutter/scramble/reverse with numeric settings
# - GIF overlay handling (best-effort; adaptor may convert GIFs if supported)
# - Plugin browser and enable/disable per-plugin (uses plugin_manager if available)
# - Speech-to-text transcription and "sentence-pooping" (text chop/shuffle) with preview
# - Background export with live logging
# - Safe fallbacks if optional modules (plugin_manager, speech_to_text) are missing
#
# Notes:
# - This GUI expects the updated ytpffmpeg_adaptor.py from the previous step.
# - Optional modules: plugin_manager.py, speech_to_text.py. If not present, GUI will still work with reduced features.
# - Tested on Python 3.10+ on Windows; FFmpeg must be in PATH for export/preview.

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import os
from pathlib import Path
import json
import time
import sys
import tempfile

from ytpffmpeg_adaptor import YTPFFmpegAdaptor

# Optional helpers
try:
    import plugin_manager as pm_mod  # provides PluginManager class
except Exception:
    pm_mod = None

try:
    import speech_to_text as stt_mod  # provides transcribe_file(path) -> str
except Exception:
    stt_mod = None


APP_TITLE = "FreePoop V2 - YTP Generator (Deluxe GUI)"


class FreePoopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1100x700")
        self.adaptor = YTPFFmpegAdaptor()
        self.presets = {}
        self._load_presets()
        self._build_ui()

    def _build_ui(self):
        # Top toolbar
        toolbar = tk.Frame(self)
        toolbar.pack(side="top", fill="x", padx=8, pady=6)

        tk.Button(toolbar, text="Add Source", command=self.add_source).pack(side="left", padx=4)
        tk.Button(toolbar, text="Add Overlay", command=self.add_overlay).pack(side="left", padx=4)
        tk.Button(toolbar, text="Transcribe (STT)", command=self.transcribe_selected).pack(side="left", padx=4)
        tk.Button(toolbar, text="Poopify Text", command=self.poopify_transcript).pack(side="left", padx=4)
        tk.Button(toolbar, text="Export", command=self.export).pack(side="left", padx=4)
        tk.Button(toolbar, text="Preview (ffplay)", command=self.preview).pack(side="left", padx=4)

        # Main panes
        main_pane = tk.PanedWindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True, padx=8, pady=6)

        left_frame = tk.Frame(main_pane)
        main_pane.add(left_frame, width=360)

        right_frame = tk.Frame(main_pane)
        main_pane.add(right_frame)

        # Left: Sources & Overlays & Plugins
        tk.Label(left_frame, text="Sources", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.lst_sources = tk.Listbox(left_frame, width=48, height=8)
        self.lst_sources.pack(padx=4, pady=4)
        src_buttons = tk.Frame(left_frame)
        src_buttons.pack(fill="x", padx=4)
        tk.Button(src_buttons, text="Remove", command=self.remove_selected_source).pack(side="left", padx=2)
        tk.Button(src_buttons, text="Move Up", command=lambda: self.move_item(self.lst_sources, -1)).pack(side="left", padx=2)
        tk.Button(src_buttons, text="Move Down", command=lambda: self.move_item(self.lst_sources, 1)).pack(side="left", padx=2)

        tk.Label(left_frame, text="Overlays", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12,0))
        self.lst_overlays = tk.Listbox(left_frame, width=48, height=6)
        self.lst_overlays.pack(padx=4, pady=4)
        ov_buttons = tk.Frame(left_frame)
        ov_buttons.pack(fill="x", padx=4)
        tk.Button(ov_buttons, text="Remove", command=self.remove_selected_overlay).pack(side="left", padx=2)
        tk.Button(ov_buttons, text="Convert GIFs (force)", command=self.convert_all_gifs).pack(side="left", padx=2)

        # Plugin area
        tk.Label(left_frame, text="Plugins", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(12,0))
        self.lst_plugins = tk.Listbox(left_frame, width=48, height=6, selectmode="extended")
        self.lst_plugins.pack(padx=4, pady=4)
        plugin_buttons = tk.Frame(left_frame)
        plugin_buttons.pack(fill="x", padx=4)
        tk.Button(plugin_buttons, text="Refresh", command=self.refresh_plugins).pack(side="left", padx=2)
        tk.Button(plugin_buttons, text="Enable Selected", command=self.enable_selected_plugins).pack(side="left", padx=2)
        tk.Button(plugin_buttons, text="Disable Selected", command=self.disable_selected_plugins).pack(side="left", padx=2)

        # Right: Effects / Transcript / Log
        top_right = tk.Frame(right_frame)
        top_right.pack(fill="x", padx=8, pady=(0,8))

        # Effects controls
        eff_frame = tk.LabelFrame(top_right, text="Effects & Presets", padx=8, pady=8)
        eff_frame.pack(side="left", fill="both", expand=True)

        self.chk_stutter = tk.IntVar(value=1 if self.adaptor.effects.get("stutter") else 0)
        tk.Checkbutton(eff_frame, text="Stutter", variable=self.chk_stutter, command=self.update_effects).grid(row=0, column=0, sticky="w")
        tk.Label(eff_frame, text="ms").grid(row=0, column=2, sticky="w")
        self.ent_stutter_ms = tk.Spinbox(eff_frame, from_=20, to=2000, increment=10, width=6, command=self.update_effects)
        self.ent_stutter_ms.delete(0, "end")
        self.ent_stutter_ms.insert(0, str(self.adaptor.effects.get("stutter_ms", 120)))
        self.ent_stutter_ms.grid(row=0, column=1, sticky="w", padx=(6,12))

        tk.Label(eff_frame, text="Repeats").grid(row=1, column=0, sticky="w")
        self.ent_stutter_repeats = tk.Spinbox(eff_frame, from_=1, to=32, width=6, command=self.update_effects)
        self.ent_stutter_repeats.delete(0, "end")
        self.ent_stutter_repeats.insert(0, str(self.adaptor.effects.get("stutter_repeats", 6)))
        self.ent_stutter_repeats.grid(row=1, column=1, sticky="w", padx=(6,12))

        self.chk_scramble = tk.IntVar(value=1 if self.adaptor.effects.get("scramble") else 0)
        tk.Checkbutton(eff_frame, text="Scramble", variable=self.chk_scramble, command=self.update_effects).grid(row=2, column=0, sticky="w")
        tk.Label(eff_frame, text="Segments").grid(row=2, column=2, sticky="w")
        self.ent_scramble_segments = tk.Spinbox(eff_frame, from_=2, to=64, width=6, command=self.update_effects)
        self.ent_scramble_segments.delete(0, "end")
        self.ent_scramble_segments.insert(0, str(self.adaptor.effects.get("scramble_segments", 8)))
        self.ent_scramble_segments.grid(row=2, column=1, sticky="w", padx=(6,12))

        self.chk_reverse = tk.IntVar(value=1 if self.adaptor.effects.get("reverse") else 0)
        tk.Checkbutton(eff_frame, text="Reverse", variable=self.chk_reverse, command=self.update_effects).grid(row=3, column=0, sticky="w")

        tk.Label(eff_frame, text="Pitch (semitones)").grid(row=4, column=0, sticky="w", pady=(8,0))
        self.sld_pitch = tk.Scale(eff_frame, from_=-12, to=12, orient="horizontal", length=220, command=self.update_pitch)
        self.sld_pitch.set(self.adaptor.effects.get("pitch_semitones", 0.0))
        self.sld_pitch.grid(row=5, column=0, columnspan=3, sticky="w")

        tk.Label(eff_frame, text="Preset").grid(row=6, column=0, sticky="w", pady=(8,0))
        self.cmb_preset = ttk.Combobox(eff_frame, state="readonly", width=30)
        self.cmb_preset['values'] = list(self.presets.keys())
        if self.presets:
            self.cmb_preset.current(0)
        self.cmb_preset.bind("<<ComboboxSelected>>", self.load_preset)
        self.cmb_preset.grid(row=6, column=1, columnspan=2, sticky="w", padx=(6,0))

        # Transcript / Poopify editor
        trans_frame = tk.LabelFrame(right_frame, text="Transcript & Text Pooping", padx=8, pady=8)
        trans_frame.pack(fill="both", expand=True, padx=8, pady=(0,8))

        upper = tk.Frame(trans_frame)
        upper.pack(fill="both", expand=True)
        left_col = tk.Frame(upper)
        left_col.pack(side="left", fill="both", expand=True, padx=(0,6))
        right_col = tk.Frame(upper)
        right_col.pack(side="left", fill="both", expand=True, padx=(6,0))

        tk.Label(left_col, text="Original Transcript").pack(anchor="w")
        self.txt_original = tk.Text(left_col, height=12)
        self.txt_original.pack(fill="both", expand=True)

        tk.Label(right_col, text="Poopified Transcript (preview)").pack(anchor="w")
        self.txt_pooped = tk.Text(right_col, height=12, bg="#fff7e6")
        self.txt_pooped.pack(fill="both", expand=True)

        # Poopify options
        poop_opts = tk.Frame(trans_frame)
        poop_opts.pack(fill="x", pady=(6,0))
        tk.Label(poop_opts, text="Shuffle intensity (0-1)").pack(side="left")
        self.sld_shuffle = tk.Scale(poop_opts, from_=0.0, to=1.0, resolution=0.05, orient="horizontal", length=200)
        self.sld_shuffle.set(0.45)
        self.sld_shuffle.pack(side="left", padx=6)
        self.chk_repeat_words = tk.IntVar(value=1)
        tk.Checkbutton(poop_opts, text="Allow repeated-word stutter", variable=self.chk_repeat_words).pack(side="left", padx=6)
        tk.Button(poop_opts, text="Apply Poopify", command=self.apply_pooped_to_adaptor).pack(side="right", padx=6)

        # Bottom: Log
        log_frame = tk.LabelFrame(self, text="Log / FFmpeg Output", padx=8, pady=8)
        log_frame.pack(fill="both", padx=8, pady=(0,8), expand=False)
        self.txt_log = tk.Text(log_frame, height=10)
        self.txt_log.pack(fill="both", expand=True)

        # Populate initial plugin list
        self.refresh_plugins()

    # ----------------- Source & Overlay management -----------------
    def add_source(self):
        fn = filedialog.askopenfilename(title="Select source video/audio",
                                        filetypes=[("Video/Audio", "*.mp4 *.mkv *.webm *.mov *.avi *.mp3 *.wav *.flac"), ("All files", "*.*")])
        if not fn:
            return
        path = Path(fn)
        try:
            local = self.adaptor.add_source(str(path))
            self.lst_sources.insert("end", str(local))
            self.log(f"Added source: {local}")
        except Exception as e:
            messagebox.showerror("Error adding source", str(e))
            self.log("Error adding source: " + str(e))

    def remove_selected_source(self):
        sel = self.lst_sources.curselection()
        if not sel:
            return
        idx = sel[0]
        item = self.lst_sources.get(idx)
        self.lst_sources.delete(idx)
        try:
            # remove from adaptor sources list (match by path string)
            p = Path(item)
            self.adaptor.sources = [s for s in self.adaptor.sources if str(s) != str(p)]
            self.log(f"Removed source: {item}")
        except Exception as e:
            self.log("Error removing source: " + str(e))

    def move_item(self, listbox: tk.Listbox, direction: int):
        sel = listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= listbox.size():
            return
        item = listbox.get(idx)
        listbox.delete(idx)
        listbox.insert(new_idx, item)
        listbox.select_set(new_idx)
        # If we moved sources, update adaptor order
        if listbox == self.lst_sources:
            self.adaptor.sources = [Path(x) for x in list(self.lst_sources.get(0, "end"))]

    def add_overlay(self):
        fn = filedialog.askopenfilename(title="Select overlay (image/gif/video)",
                                        filetypes=[("Images/GIFs", "*.png *.jpg *.jpeg *.gif"), ("Video", "*.mp4 *.webm *.mov"), ("All files", "*.*")])
        if not fn:
            return
        try:
            # Try to let adaptor handle gif conversion if it supports it
            if fn.lower().endswith(".gif") and hasattr(self.adaptor, "prepare_overlay_from_gif"):
                ov = self.adaptor.prepare_overlay_from_gif(fn)
                self.adaptor.add_overlay(str(ov))
                self.lst_overlays.insert("end", f"{ov} (converted)")
                self.log(f"Added GIF overlay (converted): {ov}")
            else:
                ov = self.adaptor.add_overlay(fn)
                self.lst_overlays.insert("end", f"{fn}")
                self.log(f"Added overlay: {fn}")
        except Exception as e:
            messagebox.showerror("Error adding overlay", str(e))
            self.log("Error adding overlay: " + str(e))

    def remove_selected_overlay(self):
        sel = self.lst_overlays.curselection()
        if not sel:
            return
        idx = sel[0]
        item = self.lst_overlays.get(idx)
        self.lst_overlays.delete(idx)
        try:
            # remove from adaptor overlays list by file match
            # overlay entries are either full path or "path (converted)"
            pathstr = item.split(" (")[0]
            self.adaptor.overlays = [o for o in self.adaptor.overlays if str(o.get("path")) != pathstr]
            self.log(f"Removed overlay: {pathstr}")
        except Exception as e:
            self.log("Error removing overlay: " + str(e))

    def convert_all_gifs(self):
        # Force conversion for all overlays that are GIFs, if adaptor supports conversion
        converted = 0
        if not hasattr(self.adaptor, "prepare_overlay_from_gif"):
            messagebox.showinfo("Not supported", "GIF conversion not available in adaptor.")
            return
        for idx in range(self.lst_overlays.size()):
            item = self.lst_overlays.get(idx)
            pathstr = item.split(" (")[0]
            if pathstr.lower().endswith(".gif"):
                try:
                    newp = self.adaptor.prepare_overlay_from_gif(pathstr)
                    self.lst_overlays.delete(idx)
                    self.lst_overlays.insert(idx, f"{newp} (converted)")
                    converted += 1
                except Exception as e:
                    self.log("GIF conversion error for " + pathstr + ": " + str(e))
        self.log(f"Converted {converted} GIF overlays.")

    # ----------------- Plugins -----------------
    def refresh_plugins(self):
        self.lst_plugins.delete(0, "end")
        if self.adaptor.plugin_manager is None:
            self.lst_plugins.insert("end", "Plugin manager not available")
            return
        try:
            plugins = self.adaptor.plugin_manager.list_plugins()
            for p in plugins:
                state = "[ENABLED]" if self.adaptor.plugin_manager.is_enabled(p) else "[disabled]"
                self.lst_plugins.insert("end", f"{p} {state}")
            self.log("Plugins refreshed.")
        except Exception as e:
            self.lst_plugins.insert("end", "Error loading plugins: " + str(e))
            self.log("Plugin refresh error: " + str(e))

    def _selected_plugin_names(self):
        sels = self.lst_plugins.curselection()
        res = []
        for i in sels:
            raw = self.lst_plugins.get(i)
            name = raw.split()[0]
            res.append(name)
        return res

    def enable_selected_plugins(self):
        if self.adaptor.plugin_manager is None:
            messagebox.showinfo("Not available", "Plugin manager not available.")
            return
        for name in self._selected_plugin_names():
            try:
                self.adaptor.plugin_manager.enable(name)
                self.log(f"Enabled plugin: {name}")
            except Exception as e:
                self.log("Error enabling plugin " + name + ": " + str(e))
        self.refresh_plugins()

    def disable_selected_plugins(self):
        if self.adaptor.plugin_manager is None:
            messagebox.showinfo("Not available", "Plugin manager not available.")
            return
        for name in self._selected_plugin_names():
            try:
                self.adaptor.plugin_manager.disable(name)
                self.log(f"Disabled plugin: {name}")
            except Exception as e:
                self.log("Error disabling plugin " + name + ": " + str(e))
        self.refresh_plugins()

    # ----------------- Effects / Presets -----------------
    def update_effects(self):
        try:
            st_ms = int(self.ent_stutter_ms.get())
        except Exception:
            st_ms = 120
        try:
            st_rep = int(self.ent_stutter_repeats.get())
        except Exception:
            st_rep = 6
        try:
            scr_seg = int(self.ent_scramble_segments.get())
        except Exception:
            scr_seg = 8

        self.adaptor.set_effect("stutter", bool(self.chk_stutter.get()))
        self.adaptor.set_effect("stutter_ms", st_ms)
        self.adaptor.set_effect("stutter_repeats", st_rep)
        self.adaptor.set_effect("scramble", bool(self.chk_scramble.get()))
        self.adaptor.set_effect("scramble_segments", scr_seg)
        self.adaptor.set_effect("reverse", bool(self.chk_reverse.get()))
        self.log("Effects updated")

    def update_pitch(self, val):
        v = float(val)
        self.adaptor.set_effect("pitch_semitones", v)
        self.log(f"Pitch set to {v} semitones")

    def load_preset(self, _evt=None):
        key = self.cmb_preset.get()
        preset = self.presets.get(key)
        if preset:
            self.adaptor.load_preset(preset)
            # update UI fields to reflect preset
            self.chk_stutter.set(1 if preset.get("stutter") else 0)
            self.ent_stutter_ms.delete(0, "end")
            self.ent_stutter_ms.insert(0, str(preset.get("stutter_ms", 120)))
            self.ent_stutter_repeats.delete(0, "end")
            self.ent_stutter_repeats.insert(0, str(preset.get("stutter_repeats", 6)))
            self.chk_scramble.set(1 if preset.get("scramble") else 0)
            self.ent_scramble_segments.delete(0, "end")
            self.ent_scramble_segments.insert(0, str(preset.get("scramble_segments", 8)))
            self.chk_reverse.set(1 if preset.get("reverse") else 0)
            self.sld_pitch.set(preset.get("pitch_semitones", 0))
            self.log(f"Loaded preset: {key}")

    # ----------------- Transcription & Poopify -----------------
    def transcribe_selected(self):
        # Transcribe first selected source or the first source
        if not self.adaptor.sources:
            messagebox.showwarning("No source", "Please add a source to transcribe.")
            return
        src = self.adaptor.sources[0]
        if stt_mod is None or not hasattr(stt_mod, "transcribe_file"):
            messagebox.showinfo("STT not available", "Speech-to-text backend not found. Install the optional speech_to_text adapter.")
            return

        def do_transcribe():
            self.log("Starting transcription (this may take a while)...")
            try:
                txt = stt_mod.transcribe_file(str(src))
                self.txt_original.delete("1.0", "end")
                self.txt_original.insert("1.0", txt)
                self.log("Transcription complete.")
            except Exception as e:
                self.log("Transcription error: " + str(e))
                messagebox.showerror("Transcription error", str(e))

        t = threading.Thread(target=do_transcribe, daemon=True)
        t.start()

    def poopify_transcript(self):
        # Basic local poisson-based shuffle / word-chop algorithm for preview only
        src_txt = self.txt_original.get("1.0", "end").strip()
        if not src_txt:
            messagebox.showwarning("No transcript", "Provide or transcribe text first.")
            return

        intensity = float(self.sld_shuffle.get())
        allow_repeats = bool(self.chk_repeat_words.get())

        pooped = self._simple_pooper(src_txt, intensity=intensity, allow_repeats=allow_repeats)
        self.txt_pooped.delete("1.0", "end")
        self.txt_pooped.insert("1.0", pooped)
        self.log("Generated pooped transcript preview.")

    def _simple_pooper(self, text: str, intensity: float = 0.5, allow_repeats: bool = True) -> str:
        """
        Turn text into a 'pooped' variant by:
          - Splitting sentences, then shuffling words inside sentences with intensity probability
          - Randomly repeating short words to emulate stutter if allow_repeats True
        This is deterministic enough for a preview but intentionally playful.
        """
        import random
        random.seed(int(time.time()) & 0xFFFF)
        sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
        out_sents = []
        for sent in sentences:
            words = sent.split()
            n = len(words)
            # compute how many swaps based on intensity
            swaps = max(1, int(n * intensity))
            for _ in range(swaps):
                if n < 2:
                    break
                i = random.randrange(n)
                j = random.randrange(n)
                words[i], words[j] = words[j], words[i]
            if allow_repeats:
                # randomly repeat some short words
                for i, w in enumerate(list(words)):
                    if len(w) <= 3 and random.random() < intensity * 0.25:
                        words.insert(i + 1, w)
            out_sents.append(" ".join(words))
        return ". ".join(out_sents) + (". " if out_sents else "")

    def apply_pooped_to_adaptor(self):
        # Apply the poopified transcript as a metadata overlay or as an effect plugin if available
        pooped = self.txt_pooped.get("1.0", "end").strip()
        if not pooped:
            messagebox.showwarning("Empty", "Generate a pooped transcript first.")
            return
        # If plugin exists that consumes sentence-pooping, hand it off
        if self.adaptor.plugin_manager and self.adaptor.plugin_manager.is_enabled("sentence_pooper"):
            try:
                self.adaptor.plugin_manager.run("sentence_pooper", text=pooped)
                self.log("Sent pooped transcript to sentence_pooper plugin.")
                messagebox.showinfo("Applied", "Sent pooped transcript to plugin pipeline.")
                return
            except Exception as e:
                self.log("Plugin sentence_pooper error: " + str(e))
        # Otherwise, store as a special effect parameter so adaptor export can use it (e.g., burned subtitles)
        self.adaptor.set_effect("sentence_pooping", True)
        # store the payload in adaptor for later use
        self.adaptor.preset_params["pooped_transcript"] = pooped
        self.log("Applied pooped transcript to adaptor's preset params (will be used at export if supported).")
        messagebox.showinfo("Applied", "Pooped transcript stored; export will include it if supported by adaptor.")

    # ----------------- Export / Preview -----------------
    def preview(self):
        # Use adaptor.preview but run in thread to avoid blocking
        try:
            self.adaptor.preview()
            self.log("Preview started (ffplay).")
        except Exception as e:
            self.log("Preview error: " + str(e))
            messagebox.showerror("Preview error", str(e))

    def export(self):
        if not self.adaptor.sources:
            messagebox.showwarning("No source", "Please add a source before exporting.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4", "*.mp4")], title="Export to")
        if not out:
            return

        # Ensure effects reflect current UI state
        self.update_effects()
        # Start background thread to run export
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

    # ----------------- Presets -----------------
    def _load_presets(self):
        try:
            here = Path(__file__).parent
            presets_file = here / "presets.json"
            if presets_file.exists():
                with open(presets_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    self.presets = data.get("presets", {})
        except Exception as e:
            # fallback: built-in small presets
            self.presets = {
                "classic (2006-2009)": {"stutter": True, "stutter_ms": 120, "stutter_repeats": 6, "scramble": True, "scramble_segments": 8, "reverse": False, "pitch_semitones": 3},
                "modern (2025)": {"stutter": True, "stutter_ms": 80, "stutter_repeats": 3, "scramble": False, "scramble_segments": 6, "reverse": True, "pitch_semitones": -5}
            }

    # ----------------- Utilities -----------------
    def log(self, text: str):
        ts = time.strftime("%H:%M:%S")
        self.txt_log.insert("end", f"[{ts}] {text}\n")
        self.txt_log.see("end")

    # ----------------- Shutdown -----------------
    def quit(self):
        # try to cleanup adaptor temp files if available
        try:
            if hasattr(self.adaptor, "cleanup"):
                self.adaptor.cleanup()
        except Exception:
            pass
        super().quit()


if __name__ == "__main__":
    app = FreePoopApp()
    app.mainloop()