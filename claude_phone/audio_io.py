"""Microphone recording (with silence-based end-of-speech detection) and playback."""

import io
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

from . import config


def record_until_silence() -> np.ndarray:
    """Record from the mic until the caller stops talking (or hits the max duration).

    Returns mono float32 samples at config.SAMPLE_RATE.
    """
    chunks = []
    silence_started_at = None
    started_at = time.time()
    speech_detected = False

    with sd.InputStream(
        samplerate=config.SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=config.INPUT_DEVICE,
    ) as stream:
        print("Listening...")
        while True:
            block, _ = stream.read(int(config.SAMPLE_RATE * 0.1))
            chunks.append(block.copy())

            volume = float(np.sqrt(np.mean(block ** 2)))
            now = time.time()

            if volume >= config.SILENCE_THRESHOLD:
                speech_detected = True
                silence_started_at = None
            elif speech_detected:
                if silence_started_at is None:
                    silence_started_at = now
                elif now - silence_started_at >= config.SILENCE_DURATION:
                    break

            if now - started_at >= config.MAX_RECORDING_SECONDS:
                break

    return np.concatenate(chunks, axis=0).flatten()


def audio_to_wav_bytes(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, config.SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()


def play_audio(audio_bytes: bytes) -> None:
    """Play back audio (any format soundfile can read, e.g. WAV) and block until done."""
    samples, samplerate = sf.read(io.BytesIO(audio_bytes), dtype="float32")
    sd.play(samples, samplerate, device=config.OUTPUT_DEVICE)
    sd.wait()
