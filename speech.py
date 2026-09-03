"""
Speech support for the Layman's Translator desktop app.

Listening is online: audio goes to OpenAI's transcription API, so speech mode
needs an internet connection and an API key. Speaking is done locally with the
macOS `say` command, which is instant and free; set "tts": "openai" in the
config to use OpenAI voices instead.

Nothing here imports Tkinter. The app drives it from a background thread.

API key, in order of precedence:
  1. OPENAI_API_KEY environment variable
  2. ~/.laymans-translator/config.json  ->  {"api_key": "sk-..."}
"""

from __future__ import annotations

import io
import json
import os
import ssl
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

CONFIG_DIR = os.path.expanduser("~/.laymans-translator")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

SAMPLE_RATE = 16000
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "alloy"
SAY_VOICE = ""          # "" uses the system default; e.g. "Samantha"
SAY_RATE = 190          # words per minute


def _ssl_context() -> ssl.SSLContext | None:
    """
    Root certificates for the API calls.

    The python.org macOS build ships without a certificate store unless you run
    its "Install Certificates.command", so a plain HTTPS request fails with
    CERTIFICATE_VERIFY_FAILED. Fall back to certifi's bundle when the system
    store has nothing in it, so speech mode works out of the box.
    """
    try:
        ctx = ssl.create_default_context()
        stats = ctx.cert_store_stats()
        if stats.get("x509_ca", 0) > 0:
            return ctx
    except Exception:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


_SSL = _ssl_context()


class SpeechError(Exception):
    """
    Anything the user needs to be told about, in plain words.

    `fatal` means speech mode cannot continue and the message deserves a
    dialog: no microphone permission, a bad key, no internet. Non-fatal ones
    ("I didn't hear anything") just go round the loop again.
    """

    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal


# --------------------------------------------------------------- config

def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_api_key(key: str) -> None:
    cfg = load_config()
    cfg["api_key"] = key.strip()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as fh:
        json.dump(cfg, fh, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def get_api_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if key and key.strip():
        return key.strip()
    key = load_config().get("api_key")
    return key.strip() if key and key.strip() else None


def audio_available() -> tuple[bool, str]:
    """Can we record at all? Returns (ok, reason-if-not)."""
    try:
        import sounddevice  # noqa: F401
    except Exception:
        return False, ("Microphone support is missing. Install it with:\n"
                       "    python3 -m pip install --user sounddevice numpy")
    return True, ""


# --------------------------------------------------------- input devices

def input_devices() -> list:
    """Every device that can capture, as (index, name)."""
    import sounddevice as sd
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0]


def _peak(device, seconds=0.25) -> int:
    """Loudest sample a device gives us in a short listen. -1 if it won't open."""
    import sounddevice as sd
    try:
        stream = sd.InputStream(device=device, samplerate=SAMPLE_RATE, channels=1,
                                dtype="int16", blocksize=int(SAMPLE_RATE * 0.05))
        with stream:
            buf, _ = stream.read(int(SAMPLE_RATE * seconds))
        return int(abs(buf).max())
    except Exception:
        return -1


def _all_silent_message(tried: list) -> str:
    names = ", ".join(name for name, _ in tried) or "none"
    if all(peak < 0 for _, peak in tried):
        return (f"No microphone would open (tried: {names}). Another app may be "
                "holding the microphone; quit it and try again.")
    return (
        f"Every microphone returned pure silence (tried: {names}).\n\n"
        "Two things cause that, and neither one looks like an error:\n\n"
        "  \u2022 Bluetooth headphones connected for playback only. AirPods expose a\n"
        "    microphone only in hands-free mode, so while they are playing audio\n"
        "    their input is a stream of zeros. Switch the input to the built-in\n"
        "    microphone under System Settings > Sound > Input.\n\n"
        "  \u2022 Microphone permission. macOS gives a blocked app silence rather than\n"
        "    refusing it. Enable this app under System Settings > Privacy &\n"
        "    Security > Microphone \u2014 launched from the .app it asks as \u201cPython\u201d,\n"
        "    launched from Terminal it asks as \u201cTerminal\u201d."
    )


def pick_input_device():
    """
    Choose a microphone that is actually delivering sound, and say which.

    The system default is not good enough on its own: a Bluetooth headset in
    playback mode is the default input and records perfect silence, so the
    recording succeeds and the transcription comes back empty. Probe first,
    prefer the default when it works, and fall back to whatever does.

    Returns (device_index, name). Raises a fatal SpeechError if nothing hears.
    """
    import sounddevice as sd

    devices = input_devices()
    if not devices:
        raise SpeechError("No microphone is connected.", fatal=True)

    by_index = dict(devices)
    try:
        default = sd.default.device[0]
    except Exception:
        default = None

    order = ([(default, by_index[default])] if default in by_index else [])
    order += [(i, n) for i, n in devices if i != default]

    tried = []
    for index, name in order:
        peak = _peak(index)
        if peak > 0:
            return index, name
        tried.append((name, peak))

    raise SpeechError(_all_silent_message(tried), fatal=True)


# -------------------------------------------------------------- recording

class Recorder:
    """
    Records one utterance: waits for you to start talking, then stops when you
    stop. Threshold is calibrated against the room's own background noise, so
    it works in a quiet room and a noisy cafe.
    """

    def __init__(self, on_state=None, device=None):
        # on_state(str) is called with "calibrating" / "waiting" / "recording".
        # device=None follows the system default; pick_input_device() gives you
        # one that is known to be delivering sound.
        self.on_state = on_state or (lambda _s: None)
        self.device = device
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def _name(self) -> str:
        try:
            import sounddevice as sd
            return sd.query_devices(self.device if self.device is not None else
                                    sd.default.device[0])["name"]
        except Exception:
            return "the default microphone"

    def record(self, max_seconds=30.0, silence_seconds=1.3, wait_seconds=12.0) -> bytes:
        """Record until silence and return 16-bit mono WAV bytes."""
        import numpy as np
        import sounddevice as sd

        self._cancel.clear()
        block = int(SAMPLE_RATE * 0.05)          # 50 ms blocks
        chunks: list = []
        heard_anything = False

        def rms(buf) -> float:
            a = buf.astype("float32")
            return float((a * a).mean() ** 0.5)

        try:
            stream = sd.InputStream(device=self.device, samplerate=SAMPLE_RATE,
                                    channels=1, dtype="int16", blocksize=block)
        except Exception as err:                  # no device, in use, etc.
            raise SpeechError(f"Could not open the microphone: {err}", fatal=True) from err

        with stream:
            # 1) Calibrate on ~0.4s of room tone.
            self.on_state("calibrating")
            ambient = []
            for _ in range(8):
                if self._cancel.is_set():
                    raise SpeechError("cancelled")
                buf, _ = stream.read(block)
                ambient.append(rms(buf[:, 0]))
                if abs(buf).max() > 0:
                    heard_anything = True
            floor = sorted(ambient)[len(ambient) // 2]
            # Speak-up threshold: comfortably above the room, with a sane minimum.
            start_level = max(floor * 3.0, 220.0)
            stop_level = max(floor * 2.0, 150.0)

            if not heard_anything and max(ambient) == 0:
                raise SpeechError(_all_silent_message([(self._name(), 0)]), fatal=True)

            # 2) Wait for speech to start.
            self.on_state("waiting")
            waited = 0.0
            while True:
                if self._cancel.is_set():
                    raise SpeechError("cancelled")
                buf, _ = stream.read(block)
                level = rms(buf[:, 0])
                if level > start_level:
                    chunks.append(buf.copy())
                    break
                waited += 0.05
                if waited > wait_seconds:
                    raise SpeechError("I didn't hear anything. Try again and speak up a little.")

            # 3) Record until it goes quiet for silence_seconds.
            self.on_state("recording")
            quiet_for = 0.0
            elapsed = 0.0
            while elapsed < max_seconds:
                if self._cancel.is_set():
                    raise SpeechError("cancelled")
                buf, _ = stream.read(block)
                chunks.append(buf.copy())
                quiet_for = quiet_for + 0.05 if rms(buf[:, 0]) < stop_level else 0.0
                elapsed += 0.05
                if quiet_for >= silence_seconds:
                    break

        audio = np.concatenate(chunks, axis=0) if chunks else np.zeros((0, 1), dtype="int16")
        if len(audio) < SAMPLE_RATE * 0.3:
            raise SpeechError("That was too short to make out. Try again.")
        return _to_wav(audio.tobytes())


def _to_wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm)
    return buf.getvalue()


# ----------------------------------------------------------- transcription

def transcribe(wav_bytes: bytes, api_key: str, timeout=45) -> str:
    """Send audio to OpenAI and return the text. This is the online part."""
    boundary = f"----lt{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: str):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )

    field("model", TRANSCRIBE_MODEL)
    # Nudges the recogniser toward the vocabulary this app cares about.
    field("prompt", "Economics terms such as inflation, GDP, opportunity cost, "
                    "the Federal Reserve, basis points, elasticity, and fiscal policy.")
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"speech.wav\"\r\nContent-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(wav_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as res:
            return (json.loads(res.read().decode()).get("text") or "").strip()
    except urllib.error.HTTPError as err:
        raise SpeechError(_http_message(err), fatal=err.code in (401, 403)) from err
    except urllib.error.URLError as err:
        if "CERTIFICATE_VERIFY_FAILED" in str(err.reason):
            raise SpeechError(
                "This Python has no root certificates, so it cannot make a secure\n"
                "connection. Fix it with either of these, then try again:\n"
                "    python3 -m pip install --user certifi\n"
                '    open "/Applications/Python 3.14/Install Certificates.command"',
                fatal=True,
            ) from err
        raise SpeechError(
            f"Could not reach OpenAI. Check your internet connection. ({err.reason})", fatal=True
        ) from err


def _http_message(err: urllib.error.HTTPError) -> str:
    try:
        detail = json.loads(err.read().decode()).get("error", {}).get("message", "")
    except Exception:
        detail = ""
    if err.code == 401:
        return "That API key was rejected. Set a valid key with the Key\u2026 button."
    if err.code == 429:
        return "OpenAI rate-limited the request, or the account is out of credit."
    return f"OpenAI returned {err.code}. {detail}".strip()


# ------------------------------------------------------------------ speech

class Speaker:
    """Speaks text aloud and can be cut off mid-sentence."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def say(self, text: str, api_key: str | None = None, use_openai=False) -> None:
        """Blocks until the sentence is finished or stop() is called."""
        text = (text or "").strip()
        if not text:
            return
        self.stop()
        if use_openai and api_key:
            try:
                self._say_openai(text, api_key)
                return
            except SpeechError:
                pass          # fall through to the local voice
        self._say_local(text)

    def _say_local(self, text: str) -> None:
        if not shutil.which("say"):
            raise SpeechError("No text-to-speech voice available on this system.")
        cmd = ["say", "-r", str(SAY_RATE)]
        if SAY_VOICE:
            cmd += ["-v", SAY_VOICE]
        cmd.append(text)
        with self._lock:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc = self._proc
        proc.wait()
        with self._lock:
            if self._proc is proc:
                self._proc = None

    def _say_openai(self, text: str, api_key: str) -> None:
        req = urllib.request.Request(
            "https://api.openai.com/v1/audio/speech",
            data=json.dumps({
                "model": TTS_MODEL,
                "voice": TTS_VOICE,
                "input": text[:4000],
                "response_format": "mp3",
            }).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45, context=_SSL) as res:
                audio = res.read()
        except urllib.error.HTTPError as err:
            raise SpeechError(_http_message(err)) from err
        except urllib.error.URLError as err:
            raise SpeechError(f"Could not reach OpenAI: {err.reason}") from err

        path = os.path.join(tempfile.gettempdir(), f"lt-{uuid.uuid4().hex}.mp3")
        try:
            with open(path, "wb") as fh:
                fh.write(audio)
            with self._lock:
                self._proc = subprocess.Popen(["afplay", path],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                proc = self._proc
            proc.wait()
            with self._lock:
                if self._proc is proc:
                    self._proc = None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    # Manual check:  python3 speech.py
    ok, why = audio_available()
    if not ok:
        sys.exit(why)
    key = get_api_key()
    print("api key:", "found" if key else "MISSING")
    device, name = pick_input_device()
    print("microphone:", name)
    r = Recorder(on_state=lambda s: print(" ", s, flush=True), device=device)
    print("Say something…")
    wav = r.record()
    print(f"captured {len(wav) / 1024:.0f} KB")
    if key:
        t0 = time.time()
        print("heard:", transcribe(wav, key), f"({time.time() - t0:.1f}s)")
    Speaker().say("Speech mode is working.")
