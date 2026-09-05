"""Hard technical backstop: verifies every LLM reply is safe to speak to a child
before it reaches TTS, via OpenAI's moderation API. Runs regardless of LLM_PROVIDER.
"""

from openai import OpenAI

from . import config

_client = OpenAI(api_key=config.OPENAI_API_KEY)


def warm_up() -> None:
    """Forces DNS/TLS/connection-pool setup at startup instead of on the first real call."""
    try:
        _client.models.list()
    except Exception as e:
        print(f"[warmup] OpenAI moderation warm-up failed (harmless, will retry on first real call): {e}")


def is_child_safe(text: str) -> bool:
    """Returns False if `text` is flagged by moderation, OR if the check itself
    fails for any reason (rate limit, network error, malformed response) -- fails
    safe rather than letting an unverified reply through.
    """
    try:
        response = _client.moderations.create(model="omni-moderation-latest", input=text)
        return not response.results[0].flagged
    except Exception as e:
        print(f"[safety] moderation check failed, treating reply as unsafe: {e}")
        return False
