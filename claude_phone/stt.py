"""Speech-to-text via either OpenAI Whisper or the Wispr Flow REST API.

Select with the STT_PROVIDER env var ("openai" or "wispr").
Wispr docs: https://api-docs.wisprflow.ai/rest_api_transcribe
Both providers accept the 16kHz WAV bytes produced by
audio_io.audio_to_wav_bytes() directly.
"""

import base64

import httpx
from openai import OpenAI

from . import config

_WISPR_API_URL = "https://platform-api.wisprflow.ai/api/v1/dash/api"

_openai_client = OpenAI(api_key=config.OPENAI_API_KEY)


def _transcribe_openai(wav_bytes: bytes) -> str:
    result = _openai_client.audio.transcriptions.create(
        model=config.STT_MODEL,
        file=("speech.wav", wav_bytes, "audio/wav"),
    )
    return result.text.strip()


def _transcribe_wispr(wav_bytes: bytes) -> str:
    if not config.WISPR_FLOW_API_KEY:
        raise RuntimeError("WISPR_FLOW_API_KEY is not set (required when STT_PROVIDER=wispr)")

    response = httpx.post(
        _WISPR_API_URL,
        headers={"Authorization": f"Bearer {config.WISPR_FLOW_API_KEY}"},
        json={
            "audio": base64.b64encode(wav_bytes).decode("ascii"),
            "language": [config.WISPR_FLOW_LANGUAGE],
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["text"].strip()


_PROVIDERS = {
    "openai": _transcribe_openai,
    "wispr": _transcribe_wispr,
}


def transcribe(wav_bytes: bytes) -> str:
    try:
        provider = _PROVIDERS[config.STT_PROVIDER]
    except KeyError:
        raise ValueError(
            f"Unknown STT_PROVIDER: {config.STT_PROVIDER!r} (expected 'openai' or 'wispr')"
        ) from None
    return provider(wav_bytes)
