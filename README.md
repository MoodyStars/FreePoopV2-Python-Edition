# FreePoop V2 — YTP Generator (starter)

This repository contains a minimal starter project for creating YouTube Poop (YTP) style videos using FFmpeg on Python 3.10 (Windows-friendly).

Features included in this starter:
- YTPFFmpegAdaptor: Python class to manage sources, overlays and basic effects.
- Simple Tkinter GUI (app.py) to add sources/overlays, toggle stutter/scramble/reverse, adjust pitch, choose presets and export.
- Presets JSON with "classic poopism" seeds.
- yt-dlp integration for downloading online sources (optional; install yt-dlp).

Requirements:
- Python 3.10
- FFmpeg present in PATH (ffmpeg and ffplay for preview)
- Optional Python packages:
  - yt-dlp (pip install yt-dlp)
  - pillow (if you add GIF-to-video conversion or image processing)

Quickstart:
1. Install Python 3.10 and FFmpeg, and make sure `ffmpeg`/`ffplay` are available on your PATH.
2. (Optional) pip install yt-dlp
3. Run the GUI:
   python app.py
4. Add a source video, optionally add overlays, adjust effects and export.

Notes & next steps:
- This is a starting point. Effects are simple and some implementations (scramble/stutter) are naive; they are provided to show how to assemble ffmpeg filter_complex strings.
- For high-quality pitch-shifting without artifacts, integrate an external library (rubberband) or a proper vocoder plugin.
- Add GIF-to-video handling (convert gifs to video streams) for accurate overlay animation.
- Expand presets and batch processing pipelines.

License: MIT-style — use/extend as you like.