import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
# Only required for their respective providers; validated at point of use,
# not here, so switching providers doesn't force you to set unused keys.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
WISPR_FLOW_API_KEY = os.environ.get("WISPR_FLOW_API_KEY", "")

PHONE_TRIGGER = os.environ.get("PHONE_TRIGGER", "keyboard")
HOOK_GPIO_PIN = int(os.environ.get("HOOK_GPIO_PIN", "17"))

INPUT_DEVICE = os.environ.get("INPUT_DEVICE") or None
OUTPUT_DEVICE = os.environ.get("OUTPUT_DEVICE") or None

# "claude" (Anthropic) or "gemini" (Google)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "claude")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")  # only used when LLM_PROVIDER=gemini
TTS_MODEL = os.environ.get("TTS_MODEL", "tts-1")
TTS_VOICE = os.environ.get("TTS_VOICE", "alloy")

# "wispr" (Wispr Flow REST API) or "openai" (Whisper)
STT_PROVIDER = os.environ.get("STT_PROVIDER", "wispr")
STT_MODEL = os.environ.get("STT_MODEL", "whisper-1")  # only used when STT_PROVIDER=openai
WISPR_FLOW_LANGUAGE = os.environ.get("WISPR_FLOW_LANGUAGE", "en")

SAMPLE_RATE = 16000
SILENCE_THRESHOLD = float(os.environ.get("SILENCE_THRESHOLD", "0.02"))
SILENCE_DURATION = float(os.environ.get("SILENCE_DURATION", "1.5"))
MAX_RECORDING_SECONDS = float(os.environ.get("MAX_RECORDING_SECONDS", "30"))

SYSTEM_PROMPT = (
    "You are the voice on the other end of a phone call. Keep replies short, "
    "conversational, and natural to hear spoken aloud -- a sentence or two "
    "unless the caller clearly wants more detail. No markdown, lists, or "
    "headers, since this is read aloud, not read on screen."
)
