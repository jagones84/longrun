"""Voice: whisper.cpp / openai-whisper STT + sherpa-onnx TTS.

Both backends are optional and auto-detected; nothing here runs unless the
/api/voice routes are hit. Extracted from ``server.py`` (JAG-373).
"""
import os
import uuid

from longrun.core.events import publish
from longrun.util import paths
from longrun.util.paths import REPO_ROOT as REPO

DATA_DIR = paths.DATA_DIR

WHISPER_BIN = os.environ.get("LONGRUN_WHISPER_BIN", "whisper-cli")
WHISPER_MODEL = os.environ.get("LONGRUN_WHISPER_MODEL", "")
SHERPA_TTS_MODEL = os.environ.get("LONGRUN_SHERPA_TTS_MODEL", "")


def _whisper_model_arg():
    """Model argument for the STT CLI: a real file path when configured as one,
    otherwise the bare name (openai-whisper resolves names from its cache)."""
    if WHISPER_MODEL and os.path.isfile(WHISPER_MODEL):
        return WHISPER_MODEL
    return WHISPER_MODEL


_whisper_style_cache = {}


def _whisper_style(bin_path):
    """'openai' if the CLI speaks openai-whisper flags (--output_format), else
    'cpp' for whisper.cpp-style CLIs (-m/-nt/-f). Detected once per process."""
    if bin_path in _whisper_style_cache:
        return _whisper_style_cache[bin_path]
    style = "cpp"
    import subprocess as sp
    try:
        out = sp.run([bin_path, "--help"], capture_output=True, text=True, timeout=15)
        blob = (out.stdout or "") + (out.stderr or "")
        style = "openai" if "output_format" in blob else "cpp"
    except Exception:
        pass
    _whisper_style_cache[bin_path] = style
    return style


def voice_status():
    """Detect whisper.cpp / openai-whisper and sherpa-onnx availability (evidence-based)."""
    import shutil
    bin_found = bool(shutil.which(WHISPER_BIN) or os.path.isfile(WHISPER_BIN))
    stt = {"backend": "whisper", "bin": WHISPER_BIN,
           "style": _whisper_style(WHISPER_BIN) if bin_found else None,
           "model": WHISPER_MODEL,
           "available": bin_found and bool(WHISPER_MODEL)}
    tts = {"backend": "sherpa-onnx", "model": SHERPA_TTS_MODEL, "available": False}
    if SHERPA_TTS_MODEL:
        try:
            import sherpa_onnx  # noqa: F401
            tts["available"] = True
        except ImportError:
            pass
    return {"stt": stt, "tts": tts}


def voice_stt(wav_path):
    """Transcribe a wav with the configured whisper CLI (openai-whisper or
    whisper.cpp style, auto-detected). Returns {text} or {error}."""
    if not wav_path or not os.path.isfile(wav_path):
        return {"error": "wav path required"}
    if not WHISPER_MODEL:
        return {"error": "whisper model not configured (LONGRUN_WHISPER_MODEL)"}
    import subprocess as sp
    import tempfile
    try:
        if _whisper_style(WHISPER_BIN) == "openai":
            with tempfile.TemporaryDirectory() as outdir:
                out = sp.run([WHISPER_BIN, "--model", _whisper_model_arg(),
                              "--output_format", "txt", "--output_dir", outdir,
                              wav_path],
                             capture_output=True, text=True, timeout=300)
                stem = os.path.splitext(os.path.basename(wav_path))[0] + ".txt"
                txt = os.path.join(outdir, stem)
                if os.path.isfile(txt):
                    with open(txt, encoding="utf-8") as _f:
                        text = _f.read().strip()
                else:
                    text = (out.stdout or "").strip()
        else:
            out = sp.run([WHISPER_BIN, "-m", WHISPER_MODEL, "-nt", "-f", wav_path],
                         capture_output=True, text=True, timeout=120)
            text = out.stdout.strip()
        publish("voice.stt", chars=len(text))
        return {"text": text}
    except Exception as e:
        return {"error": str(e)}


def voice_tts(text):
    """Synthesize speech with sherpa-onnx (VITS/piper) to a wav in data/.
    Returns {path, file, seconds} or {error}."""
    if not text.strip():
        return {"error": "text required"}
    if not SHERPA_TTS_MODEL or not os.path.isfile(SHERPA_TTS_MODEL):
        return {"error": "TTS model not configured (LONGRUN_SHERPA_TTS_MODEL)"}
    try:
        import sherpa_onnx
        import soundfile as sf
        mdir = os.path.dirname(SHERPA_TTS_MODEL)
        tokens = os.path.join(mdir, "tokens.txt")
        espeak = os.path.join(mdir, "espeak-ng-data")
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=SHERPA_TTS_MODEL, tokens=tokens,
            data_dir=espeak if os.path.isdir(espeak) else "")
        cfg = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2),
            rule_fsts="", max_num_sentences=0)
        tts = sherpa_onnx.OfflineTts(cfg)
        audio = tts.generate(text)
        os.makedirs(DATA_DIR, exist_ok=True)
        fname = "tts-%s.wav" % uuid.uuid4().hex[:8]
        path = os.path.join(DATA_DIR, fname)
        sf.write(path, audio.samples, audio.sample_rate)
        publish("voice.tts", chars=len(text), path=fname)
        return {"path": path, "file": fname,
                "seconds": round(len(audio.samples) / max(audio.sample_rate, 1), 2)}
    except Exception as e:
        return {"error": str(e)}

