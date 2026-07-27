"""Microphone recording (with silence-based end-of-speech detection) and playback."""

import io
import time
from typing import Iterable

import numpy as np
import sounddevice as sd
import soundfile as sf

from . import config


def record_until_silence(trigger) -> np.ndarray:
    """Record from the mic until the caller stops talking (or hits the max duration).

    Also stops immediately if `trigger` reports the phone was hung up mid-recording,
    so a hangup doesn't feed leftover/background audio into the STT/LLM/TTS pipeline.

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
            if trigger.poll_hung_up():
                break

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

    if not chunks:
        return np.zeros(0, dtype="float32")
    return np.concatenate(chunks, axis=0).flatten()


def audio_to_wav_bytes(samples: np.ndarray) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, samples, config.SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return buf.read()


def play_pcm_stream(chunks: Iterable[bytes], samplerate: int, trigger) -> None:
    """Plays raw mono 16-bit PCM chunks as they arrive, so playback can start before
    the whole clip has been synthesized. Stops immediately if `trigger` reports a
    hangup mid-playback.
    """
    with sd.RawOutputStream(
        samplerate=samplerate,
        channels=1,
        dtype="int16",
        device=config.OUTPUT_DEVICE,
    ) as stream:
        for chunk in chunks:
            if trigger.poll_hung_up():
                break
            if config.OUTPUT_VOLUME != 1.0:
                samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) * config.OUTPUT_VOLUME
                chunk = np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
            stream.write(chunk)
