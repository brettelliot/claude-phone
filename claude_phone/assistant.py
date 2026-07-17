from anthropic import Anthropic

from . import config

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY)


class Conversation:
    """Message history for a single phone call, reset on hangup."""

    def __init__(self):
        self._messages = []

    def ask(self, text: str) -> str:
        self._messages.append({"role": "user", "content": text})

        response = _client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1024,
            system=config.SYSTEM_PROMPT,
            messages=self._messages,
        )
        reply = "".join(block.text for block in response.content if block.type == "text")

        self._messages.append({"role": "assistant", "content": reply})
        return reply
