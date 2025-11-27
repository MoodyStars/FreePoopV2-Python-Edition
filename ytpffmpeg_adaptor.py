# ytpffmpeg_adaptor.py (Deluxe)
# Adds: project save/load, chroma key filter option, batch export support, improved GIF conversion with loop/fps,
# plugin vocoder hook support.
from __future__ import annotations
import os
import subprocess
import tempfile
import uuid
import math
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path
import random
import json

try:
    import yt_dlp
except Exception:
    yt_dlp = None

try:
    from plugin_manager import PluginManager
except Exception:
    PluginManager = None

def _safe_run(cmd: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, cwd=cwd)

def ffprobe_duration(path: Path, ffprobe_bin: str = "ffprobe") -> float:
    cmd = [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    p = _safe_run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe error: {p.stderr.strip()}")
    try:
        return float(p.stdout.strip())
    except Exception as e:
        raise RuntimeError(f"Could not parse duration: {e}")

class YTPFFmpegAdaptor:
    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffplay_bin: str = "ffplay", ffprobe_bin: str = "ffprobe", temp_dir: Optional[str] = None):
        self.ffmpeg = ffmpeg_bin
        self.ffplay = ffplay_bin
        self.ffprobe = ffprobe_bin
        self.temp_dir = Path(temp_dir or tempfile.mkdtemp(prefix="freepoop_"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.sources: List[Path] = []
        self.overlays: List[Dict] = []
        self.effects: Dict[str, Any] = {
            "stutter": False, "stutter_ms": 120, "stutter_repeats": 6,
            "scramble": False, "scramble_segments": 8, "reverse": False,
            "pitch_semitones": 0.0, "chroma_enabled": False, "chroma_similarity": 0.2, "chroma_blend": 0.1
        }
        self.preset_params: Dict[str, Any] = {}
        self.plugin_manager = PluginManager(self) if PluginManager else None
        self._seed = random.getrandbits(32)

    # ---------- sources & overlays ----------
    def add_source(self, path_or_url: str) -> Path:
        if path_or_url is None:
            raise ValueError("No path provided")
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            if yt_dlp is None:
                raise RuntimeError("yt-dlp not installed")
            opts = {"outtmpl": str(self.temp_dir / "%(id)s.%(ext)s"), "quiet": True, "no_warnings": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(path_or_url, download=True)
                filename = ydl.prepare_filename(info)
                p = Path(filename)
                if not p.exists():
                    for ext in ("mp4", "mkv", "webm", "avi"):
                        c = p.with_suffix("." + ext)
                        if c.exists():
                            p = c; break
                if not p.exists():
                    raise RuntimeError("Download succeeded but file not found")
                self.sources.append(p)
                return p
        else:
            p = Path(path_or_url)
            if not p.exists():
                raise FileNotFoundError("Source not found: " + path_or_url)
            self.sources.append(p)
            return p

    def add_overlay(self, file_path: str, x: str="(main_w-overlay_w)/2", y: str="(main_h-overlay_h)/2", start: float=0.0, duration: Optional[float]=None) -> Dict:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError("Overlay not found: " + file_path)
        ov = {"path": p, "x": x, "y": y, "start": float(start), "duration": duration}
        self.overlays.append(ov)
        return ov

    def prepare_overlay_from_gif(self, gif_path: str, loop: int = 0, fps: int = 15) -> Path:
        gif = Path(gif_path)
        if not gif.exists():
            raise FileNotFoundError("GIF not found: " + gif_path)
        out_name = self.temp_dir / (gif.stem + f"_{uuid.uuid4().hex[:8]}.mp4")
        # Use ffmpeg to convert. -ignore_loop 0 preserves the loop count on some builds,
        # but for consistent behaviour we output MP4 that loops once; chooser should repeat the overlay via enable or additional inputs if necessary.
        cmd = [
            self.ffmpeg, "-y", "-i", str(gif),
            "-r", str(fps),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            str(out_name)
        ]
        p = _safe_run(cmd)
        if p.returncode != 0:
            raise RuntimeError(f"GIF conversion failed: {p.stderr}")
        return out_name

    # ---------- project state ----------
    def export_project_state(self) -> Dict:
        # Represent sources and overlays as simple strings
        return {
            "sources": [str(s) for s in self.sources],
            "overlays": [{"path": str(o["path"]), "x": o.get("x"), "y": o.get("y"), "start": o.get("start"), "duration": o.get("duration")} for o in self.overlays],
            "effects": self.effects,
            "preset_params": self.preset_params
        }

    def load_project_state(self, data: Dict):
        self.sources = [Path(p) for p in data.get("sources", [])]
        self.overlays = []
        for o in data.get("overlays", []):
            self.overlays.append({"path": Path(o["path"]), "x": o.get("x"), "y": o.get("y"), "start": o.get("start", 0.0), "duration": o.get("duration")})
        self.effects.update(data.get("effects", {}))
        self.preset_params.update(data.get("preset_params", {}))

    # ---------- filter builders ----------
    def _build_chroma_filter(self, in_label: str, out_label: str) -> str:
        # Basic chroma key using chromakey filter (many ffmpeg builds provide chromakey)
        sim = float(self.effects.get("chroma_similarity", 0.2))
        blend = float(self.effects.get("chroma_blend", 0.1))
        # target color green #00ff00; the chromakey filter expects color like 0x00FF00
        return f"[{in_label}]chromakey=0x00FF00:{sim}:{blend}[{out_label}]"

    def _assemble_filter_complex(self) -> Tuple[str, str, str]:
        if not self.sources:
            raise RuntimeError("No sources")
        parts = []
        # start labels referencing input streams (0:v,0:a)
        v_label = "0:v"
        a_label = "0:a"
        current_v = v_label
        current_a = a_label

        # Chroma key as first video operation if enabled
        if self.effects.get("chroma_enabled"):
            ck_out = "v_chroma"
            parts.append(self._build_chroma_filter(current_v, ck_out))
            current_v = ck_out

        # reverse
        if self.effects.get("reverse"):
            parts.append(f"[{current_v}]reverse[v_rev]")
            parts.append(f"[{current_a}]areverse[a_rev]")
            current_v = "v_rev"; current_a = "a_rev"

        # stutter and scramble use robust builders (imported from earlier)
        if self.effects.get("stutter"):
            frag, out_v, out_a = self._build_stutter_filters(current_v, current_a,
                                                             int(self.effects.get("stutter_ms", 120)),
                                                             int(self.effects.get("stutter_repeats", 6)),
                                                             self.sources[0])
            parts.append(frag)
            current_v, current_a = out_v, out_a

        if self.effects.get("scramble"):
            frag, out_v, out_a = self._build_scramble_filters(current_v, current_a,
                                                              int(self.effects.get("scramble_segments", 8)),
                                                              self.sources[0])
            parts.append(frag)
            current_v, current_a = out_v, out_a

        # pitch
        if abs(float(self.effects.get("pitch_semitones", 0.0))) > 1e-6:
            pitch_frag = self._build_pitch_filter(current_a, f"{current_a}_p", float(self.effects.get("pitch_semitones", 0.0)))
            parts.append(pitch_frag)
            current_a = f"{current_a}_p"

        # overlays
        overlay_chain = f"[{current_v}]"
        for idx, ov in enumerate(self.overlays, start=1):
            ov_label = f"[{idx}:v]"
            out_label = f"ov{idx}"
            x = ov.get("x", "(main_w-overlay_w)/2")
            y = ov.get("y", "(main_h-overlay_h)/2")
            enable_expr = None
            if ov.get("start", 0) and ov.get("start") > 0:
                end = ov["start"] + (ov.get("duration") if ov.get("duration") else 99999)
                enable_expr = f"between(t,{ov['start']},{end})"
            enable = f":enable='{enable_expr}'" if enable_expr else ""
            parts.append(f"{overlay_chain}{ov_label}overlay=x={x}:y={y}{enable}[{out_label}]")
            overlay_chain = f"[{out_label}]"

        final_v_label = overlay_chain.strip("[]") if overlay_chain.startswith("[") else overlay_chain
        final_a_label = current_a
        filter_complex = ";".join(parts) if parts else ""
        return filter_complex, final_v_label, final_a_label

    # reuse robust builders from previous version (stutter/scramble/pitch)
    def _build_stutter_filters(self, input_v_label: str, input_a_label: str, stutter_ms: int, repeats: int, source_path: Path) -> Tuple[str,str,str]:
        # safe wrapper that calls previous implementation
        from copy import deepcopy
        # replicate implementation inline for compatibility
        D = ffprobe_duration(source_path, self.ffprobe)
        st_dur = min(max(stutter_ms / 1000.0, 0.02), D)
        default_start = min(1.0, max(0.0, D * 0.1))
        if default_start + st_dur > D:
            st_start = max(0.0, D - st_dur - 0.01)
        else:
            st_start = default_start
        segments = []
        if st_start > 0.001:
            segments.append(("pre", 0.0, st_start))
        segments.append(("st", st_start, st_dur))
        post_start = st_start + st_dur
        if post_start + 0.001 < D:
            segments.append(("post", post_start, D - post_start))
        frag_parts = []
        v_labels = []
        a_labels = []
        idx = 0
        def vlbl(n): return f"vseg{n}"
        def albl(n): return f"aseg{n}"
        for name, start, dur in segments:
            count = 1 if name != "st" else max(1, repeats)
            for r in range(count):
                frag_parts.append(f"[{input_v_label}]trim=start={start}:duration={dur},setpts=PTS-STARTPTS[{vlbl(idx)}]")
                frag_parts.append(f"[{input_a_label}]atrim=start={start}:duration={dur},asetpts=PTS-STARTPTS[{albl(idx)}]")
                v_labels.append(f"[{vlbl(idx)}]"); a_labels.append(f"[{albl(idx)}]")
                idx += 1
        n = len(v_labels)
        interleaved = []
        for i in range(n):
            interleaved.append(v_labels[i]); interleaved.append(a_labels[i])
        concat_block = "".join(interleaved) + f"concat=n={n}:v=1:a=1[st_v][st_a]"
        frag = ";".join(frag_parts + [concat_block])
        return frag, "st_v", "st_a"

    def _build_scramble_filters(self, input_v_label: str, input_a_label: str, segments: int, source_path: Path) -> Tuple[str,str,str]:
        D = ffprobe_duration(source_path, self.ffprobe)
        segments = max(1, segments)
        seg_dur = max(0.01, D / segments)
        frag_parts = []
        v_labels = []
        a_labels = []
        for i in range(segments):
            start = i * seg_dur
            dur = max(0.01, D - start) if i == segments - 1 else seg_dur
            frag_parts.append(f"[{input_v_label}]trim=start={start}:duration={dur},setpts=PTS-STARTPTS[v_{i}]")
            frag_parts.append(f"[{input_a_label}]atrim=start={start}:duration={dur},asetpts=PTS-STARTPTS[a_{i}]")
            v_labels.append(f"[v_{i}]"); a_labels.append(f"[a_{i}]")
        order = list(range(segments))
        rnd = random.Random(self._seed)
        rnd.shuffle(order)
        interleaved = []
        for i in order:
            interleaved.append(v_labels[i]); interleaved.append(a_labels[i])
        concat_block = "".join(interleaved) + f"concat=n={segments}:v=1:a=1[scr_v][scr_a]"
        frag = ";".join(frag_parts + [concat_block])
        return frag, "scr_v", "scr_a"

    def _build_pitch_filter(self, in_label: str, out_label: str, semitones: float, sample_rate: int = 44100) -> str:
        if abs(semitones) < 1e-6:
            return f"[{in_label}]anull[{out_label}]"
        rate_factor = 2 ** (semitones / 12.0)
        tempo = 1.0 / rate_factor
        atempo_filters = []
        remaining = tempo
        while remaining < 0.5 or remaining > 2.0:
            if remaining < 0.5:
                atempo_filters.append(0.5); remaining /= 0.5
            else:
                atempo_filters.append(2.0); remaining /= 2.0
        atempo_filters.append(remaining)
        atempo_str = ",".join([f"atempo={f:.8f}" for f in atempo_filters if abs(f-1.0) > 1e-9])
        filt = f"[{in_label}]asetrate={int(sample_rate*rate_factor)},aresample={sample_rate}"
        if atempo_str:
            filt += f",{atempo_str}"
        filt += f"[{out_label}]"
        return filt

    # ---------- generate & export ----------
    def generate_command(self, output_path: str, overwrite: bool=True, crf: int=18, preset: str="medium") -> List[str]:
        if not self.sources:
            raise RuntimeError("No sources added")
        cmd = [self.ffmpeg]
        if overwrite:
            cmd += ["-y"]
        # inputs: main + overlays
        cmd += ["-i", str(self.sources[0])]
        for ov in self.overlays:
            cmd += ["-i", str(ov["path"])]
        filter_complex, v_label, a_label = self._assemble_filter_complex()
        if filter_complex:
            cmd += ["-filter_complex", filter_complex]
            cmd += ["-map", f"[{v_label}]"]
            cmd += ["-map", f"[{a_label}]"]
        else:
            cmd += ["-map", "0:v", "-map", "0:a?"]
        # subtitles
        pooped = self.preset_params.get("pooped_transcript")
        if pooped:
            srt = self._write_srt_from_transcript(pooped)
            if srt:
                # add subtitles via subtitles filter; if filter_complex present, chain is required (best-effort)
                if filter_complex:
                    # append subtitles to filter_complex by wrapping final video label through subtitles filter
                    # due to complexity we fallback to -vf subtitles= if safe (best-effort)
                    cmd += ["-vf", f"subtitles={str(srt)}"]
                else:
                    cmd += ["-vf", f"subtitles={str(srt)}"]
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-c:a", "aac", "-b:a", "192k", str(output_path)]
        # plugin hook before returning command
        if self.plugin_manager:
            try:
                self.plugin_manager.run_hook_all("on_before_export", self, cmd)
            except Exception:
                pass
        return cmd

    def export(self, output_path: str, **ffmpeg_kwargs) -> subprocess.CompletedProcess:
        # allow vocoder plugin to run pre-processing
        if self.plugin_manager:
            try:
                self.plugin_manager.run_hook_all("on_preprocess_audio", self)
            except Exception:
                pass
        cmd = self.generate_command(output_path, **ffmpeg_kwargs)
        # allow plugins to inspect/modify the command
        if self.plugin_manager:
            try:
                self.plugin_manager.run_hook_all("on_run_export", self, cmd)
            except Exception:
                pass
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        return p

    def batch_export(self, jobs: List[Tuple[str, Dict]] ) -> List[Dict]:
        """
        jobs: list of (output_path, override_effects) - override_effects merges into self.effects for that run
        returns list of {'out': out, 'returncode': rc, 'stderr': stderr}
        """
        results = []
        for out, overrides in jobs:
            # snapshot effects
            old = dict(self.effects)
            try:
                if overrides:
                    self.effects.update(overrides)
                res = self.export(out)
                results.append({'out': out, 'returncode': res.returncode, 'stderr': res.stderr})
            finally:
                self.effects = old
        return results

    def _write_srt_from_transcript(self, text: str) -> Optional[Path]:
        try:
            lines = [ln.strip() for ln in text.replace("\r", "").split("\n") if ln.strip()]
            if not lines:
                return None
            sents = []
            for ln in lines:
                for s in ln.split("."):
                    s = s.strip()
                    if s:
                        sents.append(s)
            if not sents:
                sents = lines
            per = 3.0
            srt_path = self.temp_dir / (f"pooped_{uuid.uuid4().hex[:8]}.srt")
            with srt_path.open("w", encoding="utf-8") as fh:
                for i, s in enumerate(sents, start=1):
                    start = (i - 1) * per
                    end = start + per
                    def fmt(t):
                        h = int(t // 3600); m = int((t % 3600)//60); ssec = int(t%60); ms = int((t-int(t))*1000)
                        return f"{h:02d}:{m:02d}:{ssec:02d},{ms:03d}"
                    fh.write(f"{i}\n{fmt(start)} --> {fmt(end)}\n{s}\n\n")
            return srt_path
        except Exception:
            return None

    def preview(self):
        if not self.sources:
            raise RuntimeError("No source")
        subprocess.Popen([self.ffplay, "-autoexit", "-nodisp", str(self.sources[0])])

    def cleanup(self):
        try:
            for p in list(self.temp_dir.iterdir()):
                try: p.unlink()
                except Exception: pass
            try: self.temp_dir.rmdir()
            except Exception: pass
        except Exception:
            pass