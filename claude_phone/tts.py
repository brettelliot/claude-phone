from openai import OpenAI

from . import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)


def synthesize(text: str) -> bytes:
    """Returns WAV audio bytes for the given text."""
    response = _client.audio.speech.create(
        model=config.TTS_MODEL,
        voice=config.TTS_VOICE,
        input=text,
        response_format="wav",
    )
    return response.read()
