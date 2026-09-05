"""Microphone recording (with silence-based end-of-speech detection) and playback."""

import io
import queue
import threading
import time
from typing import Callable, Iterable

import numpy as np
import sounddevice as sd
import soundfile as sf

from . import comfort_noise, config


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


def _scale_volume(chunk: bytes) -> bytes:
    if config.OUTPUT_VOLUME == 1.0:
        return chunk
    samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) * config.OUTPUT_VOLUME
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()


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
            stream.write(_scale_volume(chunk))


_WORKER_DONE = object()


def play_with_comfort_noise(produce_chunks: Callable[[], Iterable[bytes]], samplerate: int, trigger) -> None:
    """Runs `produce_chunks` on a background thread. Until it yields its first chunk,
    plays quiet comfort noise instead of dead air; once real chunks start arriving,
    plays those instead, with no gap. Any exception raised inside
    `produce_chunks` is re-raised here after the background thread finishes producing
    (or is abandoned, if the call was hung up first). Stops immediately, whether
    mid-comfort-noise or mid-reply, if `trigger` reports a hangup.

    If `config.COMFORT_NOISE_ENABLED` is false, just runs `produce_chunks` synchronously
    through `play_pcm_stream`, preserving the original silent-wait behavior exactly.
    """
    if not config.COMFORT_NOISE_ENABLED:
        play_pcm_stream(produce_chunks(), samplerate, trigger)
        return

    q: "queue.Queue" = queue.Queue()

    def worker():
        try:
            for chunk in produce_chunks():
                q.put(chunk)
        except Exception as e:
            q.put(e)
            return
        q.put(_WORKER_DONE)

    threading.Thread(target=worker, daemon=True).start()

    comfort = comfort_noise.loop_chunks(samplerate)
    error = None
    draining_reply = False
    with sd.RawOutputStream(
        samplerate=samplerate,
        channels=1,
        dtype="int16",
        device=config.OUTPUT_DEVICE,
    ) as stream:
        while True:
            if trigger.poll_hung_up():
                break

            if draining_reply:
                try:
                    item = q.get(timeout=0.1)
                except queue.Empty:
                    continue
            else:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    stream.write(_scale_volume(next(comfort)))
                    continue

            if item is _WORKER_DONE:
                break
            if isinstance(item, Exception):
                error = item
                break
            draining_reply = True
            stream.write(_scale_volume(item))

    if error is not None:
        raise error
