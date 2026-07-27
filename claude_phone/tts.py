from typing import Iterator

from openai import OpenAI, RateLimitError

from . import config
from .errors import QuotaExceededError

_client = OpenAI(api_key=config.OPENAI_API_KEY)

PCM_SAMPLE_RATE = 24000


def warm_up() -> None:
    """Forces DNS/TLS/connection-pool setup at startup instead of on the first real call."""
    try:
        _client.models.list()
    except Exception as e:
        print(f"[warmup] OpenAI TTS warm-up failed (harmless, will retry on first real call): {e}")


def synthesize_stream(text: str, chunk_size: int = 4096) -> Iterator[bytes]:
    """Yields raw 24kHz mono 16-bit PCM chunks as they arrive, so playback can start
    before the whole clip is synthesized.
    """
    try:
        with _client.audio.speech.with_streaming_response.create(
            model=config.TTS_MODEL,
            voice=config.TTS_VOICE,
            input=text,
            response_format="pcm",
        ) as response:
            yield from response.iter_bytes(chunk_size=chunk_size)
    except RateLimitError as e:
        raise QuotaExceededError("OpenAI TTS", e.message) from e
