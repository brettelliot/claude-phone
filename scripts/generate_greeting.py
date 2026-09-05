"""Generates the pre-recorded greeting audio asset(s).

Run this whenever the greeting text, TTS_VOICE, or TTS_MODEL changes, then
commit the resulting file(s) in assets/greetings/. The app never calls this
at runtime -- it just plays whatever is on disk.

Usage:
    python scripts/generate_greeting.py            # regenerate every provider's greeting
    python scripts/generate_greeting.py gemini      # regenerate just one provider
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_phone import config, tts

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "greetings"


def generate(provider: str) -> None:
    text = config.GREETINGS[provider]
    audio = b"".join(tts.synthesize_stream(text))
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    path = ASSETS_DIR / f"{provider}.pcm"
    path.write_bytes(audio)
    print(f"wrote {path} ({len(audio)} bytes) for text: {text!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "provider",
        nargs="?",
        choices=sorted(config.GREETINGS),
        help="provider to regenerate (default: all providers)",
    )
    args = parser.parse_args()

    providers = [args.provider] if args.provider else sorted(config.GREETINGS)
    for provider in providers:
        generate(provider)


if __name__ == "__main__":
    main()
