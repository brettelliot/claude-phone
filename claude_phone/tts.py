from openai import OpenAI, RateLimitError

from . import config
from .errors import QuotaExceededError

_client = OpenAI(api_key=config.OPENAI_API_KEY)


def synthesize(text: str) -> bytes:
    """Returns WAV audio bytes for the given text."""
    try:
        response = _client.audio.speech.create(
            model=config.TTS_MODEL,
            voice=config.TTS_VOICE,
            input=text,
            response_format="wav",
        )
    except RateLimitError as e:
        raise QuotaExceededError("OpenAI TTS", e.message) from e
    return response.read()
