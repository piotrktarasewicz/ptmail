"""Krótkie dźwięki programu. Tony powstają w kodzie, więc repozytorium nie ma plików audio."""

import array
import io
import math
import wave
import winsound

from .config import config_path

SAMPLE_RATE = 22050
VOLUME = 0.25
FADE_SECONDS = 0.01
# Pary (częstotliwość w Hz, czas w sekundach).
SYNCED = "synced"
NEW_MAIL = "new_mail"
TONES = {
    SYNCED: ((880, 0.07),),
    NEW_MAIL: ((660, 0.1), (880, 0.14)),
}


def build_wav(tones):
    samples = array.array("h")
    for frequency, seconds in tones:
        count = int(SAMPLE_RATE * seconds)
        fade = int(SAMPLE_RATE * FADE_SECONDS)
        for index in range(count):
            # Wygaszanie brzegów usuwa trzask na początku i końcu tonu.
            envelope = min(1, index / fade, (count - index) / fade)
            value = math.sin(2 * math.pi * frequency * index / SAMPLE_RATE)
            samples.append(int(value * envelope * VOLUME * 32767))
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(SAMPLE_RATE)
        file.writeframes(samples.tobytes())
    return output.getvalue()


def _sound_path(name):
    path = config_path().parent / "sounds" / f"{name}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(build_wav(TONES[name]))
    return path


def play(name):
    try:
        winsound.PlaySound(
            str(_sound_path(name)),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except (OSError, RuntimeError):
        pass
