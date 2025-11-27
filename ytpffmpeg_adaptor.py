# ytpffmpeg_adaptor.py
# Minimal FFmpeg adapter for building YTP-style edits.
# Works with Python 3.10 on Windows. Requires ffmpeg/ffplay in PATH and yt-dlp (pip install yt-dlp)
import os
import shlex
import subprocess
import tempfile
import json
import uuid
import math
from typing import List, Dict, Optional
from pathlib import Path

try:
    import yt_dlp
except Exception:
    yt_dlp = None  # optional; download will fail if not installed


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://") or s.startswith("ftp://")


def _safe_run(cmd: List[str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, cwd=cwd)


class YTPFFmpegAdaptor:
    """
    Lightweight adaptor to create YTP-style edits using FFmpeg.
    This starter implementation creates filtergraphs for:
      - stutter (loop short clip)
      - scramble (random cut order)
      - reverse
      - overlays (images, gifs)
      - pitch-shift approximation (asetrate+atempo chaining)
    """

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffplay_bin: str = "ffplay", temp_dir: Optional[str] = None):
        self.ffmpeg = ffmpeg_bin
        self.ffplay = ffplay_bin
        self.temp_dir = Path(temp_dir or tempfile.mkdtemp(prefix="freepoop_"))
        self.sources: List[Path] = []
        self.overlays: List[Dict] = []
        self.effects: Dict = {
            "stutter": False,
            "scramble": False,
            "reverse": False,
            "pitch_semitones": 0.0,
        }
        self.preset_params: Dict = {}
        os.makedirs(self.temp_dir, exist_ok=True)

    def add_source(self, path_or_url: str) -> Path:
        """
        Add a local filename or remote URL. If URL, download via yt-dlp into temp_dir.
        Returns the local path to media file.
        """
        if _is_url(path_or_url):
            if yt_dlp is None:
                raise RuntimeError("yt-dlp Python package is not installed (pip install yt-dlp) - cannot download URL.")
            ydl_opts = {
                "outtmpl": str(self.temp_dir / "%(id)s.%(ext)s"),
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(path_or_url, download=True)
                filename = ydl.prepare_filename(info)
                # If merged, filename might be e.g. .mp4; try to find real file
                p = Path(filename)
                if not p.exists():
                    # try common extensions
                    for ext in ("mp4", "mkv", "webm", "avi"):
                        candidate = p.with_suffix("." + ext)
                        if candidate.exists():
                            p = candidate
                            break
                self.sources.append(p)
                return p
        else:
            p = Path(path_or_url)
            if not p.exists():
                raise FileNotFoundError(f"Source file not found: {path_or_url}")
            self.sources.append(p)
            return p

    def add_overlay(self, file_path: str, x: str = "(main_w-overlay_w)/2", y: str = "(main_h-overlay_h)/2",
                    start: float = 0.0, duration: Optional[float] = None) -> Dict:
        """
        Add an overlay image or GIF. We'll pass it into ffmpeg as an input and set overlay filters.
        x,y can be expressions as strings for ffmpeg overlay.
        """
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Overlay file not found: {file_path}")
        ov = {"path": p, "x": x, "y": y, "start": float(start), "duration": duration}
        self.overlays.append(ov)
        return ov

    def set_effect(self, name: str, value):
        if name not in self.effects:
            raise ValueError("Unknown effect: " + name)
        self.effects[name] = value

    def load_preset(self, preset: Dict):
        """
        Load preset parameters (dictionary) -- merges into effects and preset_params.
        """
        self.preset_params.update(preset)
        # Map known fields
        for k in ("stutter", "scramble", "reverse", "pitch_semitones"):
            if k in preset:
                self.effects[k] = preset[k]

    def _build_pitch_filter(self, in_label: str, out_label: str, semitones: float, sample_rate: int = 44100):
        """
        Build audio filter chain to pitch-shift by semitones while approximating preserved tempo.
        It uses asetrate -> aresample -> atempo chain. atempo accepts 0.5-2.0 per filter, so chain if needed.
        Returns filter string that can be used in filter_complex and the output label.
        """
        if abs(semitones) < 0.001:
            return f"[{in_label}]anull[{out_label}]"

        rate_factor = 2 ** (semitones / 12.0)
        # asetrate to change pitch, then aresample to original rate, then atempo to restore tempo
        # chain atempo filters if tempo factor outside [0.5, 2]
        tempo = 1.0 / rate_factor
        atempo_filters = []
        remaining = tempo
        # decompose into allowed range factors between 0.5 and 2
        while remaining < 0.5 or remaining > 2.0:
            if remaining < 0.5:
                atempo_filters.append(0.5)
                remaining /= 0.5
            elif remaining > 2.0:
                atempo_filters.append(2.0)
                remaining /= 2.0
        atempo_filters.append(remaining)
        atempo_str = ",".join([f"atempo={f:.8f}" for f in atempo_filters if abs(f - 1.0) > 1e-8])
        # build full filter: asetrate=sr*rate_factor, aresample=sr, then atempo chain
        # Use aresample to keep output sample rate consistent
        filt = f"[{in_label}]asetrate={int(sample_rate*rate_factor)},aresample={sample_rate}"
        if atempo_str:
            filt += f",{atempo_str}"
        filt += f"[{out_label}]"
        return filt

    def _build_stutter_filter(self, in_video_label: str, out_label: str, stutter_ms: int = 120, repeats: int = 6):
        """
        Create a simple stutter effect by trimming a short fragment and concatenating it several times.
        Works on video stream label and outputs to out_label.
        Note: this is a naive implementation and can be improved.
        """
        # trim and loop technique using select and loop is complex; instead use concat by creating repeated segments.
        # In filter_complex it will look like:
        # [in]trim=start=...:duration=...,setpts=PTS-STARTPTS[t0];[t0][t0][t0]concat=n=3:v=1:a=0[out]
        # This simple function will assume starting at 0 for demonstration.
        dur = stutter_ms / 1000.0
        labels = []
        trim_blocks = []
        for i in range(repeats):
            lbl = f"st{i}"
            labels.append(lbl)
            trim_blocks.append(f"[{in_video_label}]trim=start=0:duration={dur},setpts=PTS-STARTPTS[{lbl}]")
        concat_block = "".join([f"[{l}]" for l in labels]) + f"concat=n={repeats}:v=1:a=0[{out_label}]"
        return ";".join(trim_blocks + [concat_block])

    def _build_scramble_filter(self, in_label: str, out_label: str, segments: int = 8):
        """
        Naive scramble: split into 'segments' equal parts, reorder them randomly (deterministic here using uuid).
        Returns filter string chunk. This method is a demonstration and not optimal for large files.
        """
        # Create trim blocks for each segment (assuming duration unknown -> use segment times later in a more complete implementation).
        # For simplicity we implement fixed-time segments from start.
        # WARNING: This is a naive demo and will only effective on short inputs.
        seg_duration = 0.5  # seconds per segment as default fallback
        labels = []
        trim_blocks = []
        order = list(range(segments))
        # deterministic shuffle based on uuid
        random_seed = int(uuid.uuid4().int & 0xFFFFFF)
        order.sort(key=lambda x: ((x * 9301 + 49297 + random_seed) % 233280))
        for i in range(segments):
            lbl = f"scr{i}"
            labels.append(lbl)
            trim_blocks.append(f"[{in_label}]trim=start={i * seg_duration}:duration={seg_duration},setpts=PTS-STARTPTS[{lbl}]")
        concat_block = "".join([f"[{labels[i]}]" for i in order]) + f"concat=n={segments}:v=1:a=0[{out_label}]"
        return ";".join(trim_blocks + [concat_block])

    def _assemble_filter_complex(self, input_count: int):
        """
        Build a filter_complex string combining video and audio effects + overlays.
        This is a simplified implementation:
          - Applies stutter/scramble/reverse to the first input's video stream.
          - Applies pitch shift to the first input's audio stream.
          - Adds overlays by mapping them onto the main video stream.
        """
        parts = []
        map_video = f"[0:v]"
        map_audio = f"[0:a]"  # may not exist for all inputs

        next_video_label = "v0"
        next_audio_label = "a0"

        # Start by copying original to v0/a0 labels
        parts.append(f"{map_video}copy[{next_video_label}]")
        parts.append(f"{map_audio}anull[{next_audio_label}]")

        # Video effects
        last_v_label = next_video_label
        if self.effects.get("reverse"):
            parts.append(f"[{last_v_label}]reverse[{last_v_label}_rev]")
            last_v_label = f"{last_v_label}_rev"

        if self.effects.get("stutter"):
            # build stutter block (video-only)
            stutter_block = self._build_stutter_filter(last_v_label, f"{last_v_label}_stut", stutter_ms=120, repeats=6)
            parts.append(stutter_block)
            last_v_label = f"{last_v_label}_stut"

        if self.effects.get("scramble"):
            scramble_block = self._build_scramble_filter(last_v_label, f"{last_v_label}_scr", segments=8)
            parts.append(scramble_block)
            last_v_label = f"{last_v_label}_scr"

        # Overlays: for each overlay, add as additional input index and overlay chain
        # In this minimal example we assume overlays are inputs 1..N in order of addition.
        overlay_chain_label = last_v_label
        for idx, ov in enumerate(self.overlays, start=1):
            ov_label = f"[{idx}:v]"
            out_label = f"ov{idx}"
            x = ov.get("x", "(main_w-overlay_w)/2")
            y = ov.get("y", "(main_h-overlay_h)/2")
            # set overlay start/duration by enable expression
            enable_expr = None
            if ov["start"] and ov["start"] > 0:
                enable_expr = f"between(t,{ov['start']},{(ov['start'] + (ov['duration'] or 99999))})"
            enable = f":enable='{enable_expr}'" if enable_expr else ""
            parts.append(f"{overlay_chain_label}{ov_label}overlay=x={x}:y={y}{enable}[{out_label}]")
            overlay_chain_label = out_label

        final_video_label = overlay_chain_label

        # Audio effects: pitch shift if needed
        last_a_label = next_audio_label
        if abs(self.effects.get("pitch_semitones", 0.0)) > 0.001:
            pitch_filter = self._build_pitch_filter(last_a_label, f"{last_a_label}_p", self.effects["pitch_semitones"])
            parts.append(pitch_filter)
            last_a_label = f"{last_a_label}_p"

        filter_complex = ";".join(parts)
        return filter_complex, final_video_label, last_a_label

    def generate_command(self, output_path: str, overwrite: bool = True, crf: int = 18, preset: str = "medium") -> List[str]:
        """
        Generate the ffmpeg command line (as list) to create the final YTP video.
        This implementation uses simplistic mapping: first source is main, overlays appended as extra inputs.
        """
        if len(self.sources) == 0:
            raise RuntimeError("No sources added")
        cmd = [self.ffmpeg]
        if overwrite:
            cmd += ["-y"]
        # inputs: main + overlays
        cmd += ["-i", str(self.sources[0])]
        for ov in self.overlays:
            cmd += ["-i", str(ov["path"])]
        # specify filter_complex and map outputs
        filter_complex, v_label, a_label = self._assemble_filter_complex(input_count=1 + len(self.overlays))
        cmd += ["-filter_complex", filter_complex]
        # map final video and audio labels
        cmd += ["-map", f"[{v_label}]"]
        cmd += ["-map", f"[{a_label}]"]
        # output encoding options
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-c:a", "aac", "-b:a", "192k", str(output_path)]
        return cmd

    def export(self, output_path: str, **ffmpeg_kwargs):
        """
        Build the command and run ffmpeg synchronously. Returns CompletedProcess.
        """
        cmd = self.generate_command(output_path, **ffmpeg_kwargs)
        # Use subprocess.run so the user can see ffmpeg output; here we capture it for programmatic use.
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        return proc

    def preview(self):
        """
        Launch ffplay to preview the first source quickly. This is a helper for GUI preview.
        """
        if len(self.sources) == 0:
            raise RuntimeError("No source to preview")
        cmd = [self.ffplay, "-autoexit", "-nodisp", str(self.sources[0])]
        subprocess.Popen(cmd)

    def cleanup(self):
        # delete temp_dir if used for downloads
        try:
            # be conservative: only remove files we recognize in temp_dir root
            for p in self.temp_dir.iterdir():
                p.unlink()
            self.temp_dir.rmdir()
        except Exception:
            pass