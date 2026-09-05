"""Procedurally generated R2D2-style comfort noise, played while the caller waits for a
reply. Chirp pitch, duration, and spacing are drawn randomly within tuned ranges forever,
grouped into short "phrases" separated by a longer pause -- so unlike a looped fixed
clip, it never repeats the same sequence twice. Each chirp fades in/out to silence and
gaps are literal silence, so nothing ever needs crossfading to stay click-free.
"""

from typing import Iterator

import numpy as np

from . import config

FREQ_LO_HZ, FREQ_HI_HZ = 320.0, 2700.0
CHIRP_DUR_LO_S, CHIRP_DUR_HI_S = 0.10, 0.32
GAP_LO_S, GAP_HI_S = 0.05, 0.14
PHRASE_CHIRPS_LO, PHRASE_CHIRPS_HI = 5, 11
PHRASE_PAUSE_LO_S, PHRASE_PAUSE_HI_S = 0.4, 0.9


def _make_chirp(samplerate: int, start_hz: float, end_hz: float, duration_s: float) -> np.ndarray:
    """A short pitched sweep with a bit of odd-harmonic 'buzz' for a synth-droid timbre."""
    n = max(int(duration_s * samplerate), 1)
    t = np.arange(n) / samplerate
    if end_hz == start_hz:
        inst_freq = np.full(n, start_hz)
    else:
        ratio = end_hz / start_hz
        inst_freq = start_hz * (ratio ** (t / duration_s))
    phase = 2 * np.pi * np.cumsum(inst_freq) / samplerate
    wave = 0.75 * np.sin(phase) + 0.25 * np.sin(3 * phase)

    attack = min(int(0.005 * samplerate), n // 4) or 1
    wave[:attack] *= np.linspace(0, 1, attack)
    wave[-attack:] *= np.linspace(1, 0, attack)
    return wave


def _sample_stream(rng: np.random.Generator, samplerate: int) -> Iterator[np.ndarray]:
    """Yields variable-length float sample arrays (chirps, gaps, phrase pauses) forever,
    with randomized pitch/timing on every chirp -- never the same sequence twice.
    """
    while True:
        n_chirps = rng.integers(PHRASE_CHIRPS_LO, PHRASE_CHIRPS_HI + 1)
        for _ in range(n_chirps):
            start_hz = rng.uniform(FREQ_LO_HZ, FREQ_HI_HZ)
            end_hz = rng.uniform(FREQ_LO_HZ, FREQ_HI_HZ)
            duration_s = rng.uniform(CHIRP_DUR_LO_S, CHIRP_DUR_HI_S)
            yield _make_chirp(samplerate, start_hz, end_hz, duration_s) * config.COMFORT_NOISE_VOLUME
            yield np.zeros(int(rng.uniform(GAP_LO_S, GAP_HI_S) * samplerate))
        yield np.zeros(int(rng.uniform(PHRASE_PAUSE_LO_S, PHRASE_PAUSE_HI_S) * samplerate))


def loop_chunks(samplerate: int, chunk_ms: int = 100) -> Iterator[bytes]:
    """Yields comfort noise forever, sliced into ~chunk_ms int16 PCM byte pieces. Each
    call gets its own randomized, never-repeating chirp sequence (unseeded RNG), so
    successive waits within the same call don't sound like the same clip looping.
    """
    rng = np.random.default_rng()
    samples = _sample_stream(rng, samplerate)
    chunk_size = int(samplerate * chunk_ms / 1000)

    buffer = np.zeros(0, dtype=np.float64)
    while True:
        while len(buffer) < chunk_size:
            buffer = np.concatenate([buffer, next(samples)])
        chunk, buffer = buffer[:chunk_size], buffer[chunk_size:]
        pcm = np.clip(chunk * 32767, -32768, 32767).astype(np.int16)
        yield pcm.tobytes()
