"""LLM replies via either Anthropic Claude or Google Gemini.

Select with the LLM_PROVIDER env var ("claude" or "gemini"). Conversation
history is kept in a provider-neutral form (role "user"/"assistant" + text)
and translated to each SDK's native message format at call time.
"""

from anthropic import Anthropic
from google import genai
from google.genai import types

from . import config

_anthropic_client = None
_gemini_client = None


def _get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (required when LLM_PROVIDER=claude)")
        _anthropic_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set (required when LLM_PROVIDER=gemini)")
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


def _ask_claude(messages: list[dict]) -> str:
    response = _get_anthropic_client().messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=config.SYSTEM_PROMPT,
        messages=messages,
    )
    return "".join(block.text for block in response.content if block.type == "text")


def _ask_gemini(messages: list[dict]) -> str:
    contents = [
        types.Content(
            role="model" if message["role"] == "assistant" else "user",
            parts=[types.Part(text=message["content"])],
        )
        for message in messages
    ]
    response = _get_gemini_client().models.generate_content(
        model=config.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=config.SYSTEM_PROMPT),
    )
    return response.text.strip()


_PROVIDERS = {
    "claude": _ask_claude,
    "gemini": _ask_gemini,
}


class Conversation:
    """Message history for a single phone call, reset on hangup."""

    def __init__(self):
        self._messages = []
        try:
            self._ask = _PROVIDERS[config.LLM_PROVIDER]
        except KeyError:
            raise ValueError(
                f"Unknown LLM_PROVIDER: {config.LLM_PROVIDER!r} (expected 'claude' or 'gemini')"
            ) from None

    def ask(self, text: str) -> str:
        self._messages.append({"role": "user", "content": text})
        reply = self._ask(self._messages)
        self._messages.append({"role": "assistant", "content": reply})
        return reply
