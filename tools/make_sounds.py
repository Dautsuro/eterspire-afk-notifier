"""Generates the built-in alert sounds (eterspire_notifier/sounds/*.wav).

Run once: python tools/make_sounds.py
"""

import wave
from pathlib import Path

import numpy as np

RATE = 44100
OUT = Path(__file__).resolve().parent.parent / "eterspire_notifier" / "sounds"


def bell(freq: float, length: float, start: float, total: float) -> np.ndarray:
    t = np.arange(int(total * RATE)) / RATE
    local = t - start
    env = np.where(local >= 0, np.exp(-np.clip(local, 0, None) * 5 / length), 0.0)
    env *= np.clip(local * 200, 0, 1)  # 5 ms attack, no click
    tone = np.sin(2 * np.pi * freq * local) + 0.35 * np.sin(2 * np.pi * freq * 2 * local) + 0.1 * np.sin(2 * np.pi * freq * 3 * local)
    return env * tone


def write(name: str, signal: np.ndarray) -> None:
    signal = signal / np.abs(signal).max() * 0.8
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes((signal * 32767).astype("<i2").tobytes())


# Inventory full: three rising notes (C5 E5 G5), hard to miss.
write("inventory_full", sum(bell(f, 0.6, i * 0.16, 1.2) for i, f in enumerate((523.25, 659.25, 783.99))))
# Fishing spot empty: two soft falling notes, less insistent since it's frequent.
write("spot_empty", sum(bell(f, 0.5, i * 0.18, 0.9) for i, f in enumerate((880.0, 659.25))))
