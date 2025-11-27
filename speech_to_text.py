# speech_to_text.py (Deluxe)
# Uses faster-whisper (preferred) -> whisper -> SpeechRecognition (pocketsphinx/google) fallback.
from __future__ import annotations
import os, tempfile, subprocess
from pathlib import Path
from typing import List, Dict, Optional

# try faster-whisper
_HAS_FAST_WHISPER = False
try:
    from faster_whisper import WhisperModel
    _HAS_FAST_WHISPER = True
except Exception:
    _HAS_FAST_WHISPER = False

# try openai/whisper
_HAS_WHISPER = False
try:
    import whisper
    _HAS_WHISPER = True
except Exception:
    _HAS_WHISPER = False

# speech_recognition fallback
_HAS_SR = False
try:
    import speech_recognition as sr
    _HAS_SR = True
except Exception:
    _HAS_SR = False

# pocketsphinx availability
_HAS_POCKETS = False
if _HAS_SR:
    try:
        import pocketsphinx  # type: ignore
        _HAS_POCKETS = True
    except Exception:
        _HAS_POCKETS = False

def _ensure_wav(in_path: str, out_wav: str, ffmpeg_bin: str = "ffmpeg"):
    cmd = [ffmpeg_bin, "-y", "-i", str(in_path), "-ar", "16000", "-ac", "1", "-vn", "-f", "wav", str(out_wav)]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg convert failed: " + p.stderr)

def transcribe_file(path: str, model: str = "small", device: str = "cpu", ffmpeg_bin: str = "ffmpeg") -> str:
    src = Path(path)
    if not src.exists():
        raise FileNotFoundError("File not found: " + path)

    # faster-whisper branch
    if _HAS_FAST_WHISPER:
        try:
            # streaming decode with faster-whisper is efficient
            m = WhisperModel(model, device=device, compute_type="float32")
            segments, info = m.transcribe(str(src))
            text = " ".join([s.text for s in segments])
            return text.strip()
        except Exception as e:
            print(f"[stt] faster-whisper error, falling back: {e}")

    if _HAS_WHISPER:
        try:
            m = whisper.load_model(model)
            res = m.transcribe(str(src))
            return res.get("text", "").strip()
        except Exception as e:
            print(f"[stt] whisper error, falling back: {e}")

    # speech_recognition fallback
    if _HAS_SR:
        r = sr.Recognizer()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_wav = tmp.name
        try:
            _ensure_wav(str(src), tmp_wav, ffmpeg_bin=ffmpeg_bin)
            with sr.AudioFile(tmp_wav) as af:
                audio = r.record(af)
            if _HAS_POCKETS:
                try:
                    return r.recognize_sphinx(audio).strip()
                except Exception as e:
                    print(f"[stt] pocketsphinx error: {e}")
            try:
                return r.recognize_google(audio).strip()
            except Exception as e:
                raise RuntimeError("SpeechRecognition (Google) failed: " + str(e))
        finally:
            try: os.unlink(tmp_wav)
            except Exception: pass

    raise RuntimeError("No STT backend available. Install faster-whisper/whisper or speech_recognition (+pocketsphinx).")

def transcribe_batch(paths: List[str], model: str = "small", device: str = "cpu") -> Dict[str,str]:
    results = {}
    for p in paths:
        try:
            results[p] = transcribe_file(p, model=model, device=device)
        except Exception as e:
            results[p] = f"ERROR: {e}"
    return results