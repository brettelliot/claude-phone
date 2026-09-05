import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import audio_io, config, stt, tts
from .assistant import Conversation
from .errors import ModelOverloadedError, QuotaExceededError
from .trigger import get_trigger

# When stdout isn't a terminal (e.g. piped to journald under systemd), Python
# fully block-buffers it, so prints only reach the journal in bursts on exit
# instead of live. Force line buffering so `journalctl -f` shows lines as they
# happen. This is independent of PYTHONUNBUFFERED so it works regardless of
# how the process is launched.
sys.stdout.reconfigure(line_buffering=True)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "greetings"


def _load_greeting_audio(provider: str) -> bytes:
    """Loads the pre-recorded greeting for `provider` so it can be played with zero
    TTS latency at pickup. Generate/refresh it with scripts/generate_greeting.py.
    """
    path = ASSETS_DIR / f"{provider}.pcm"
    if not path.exists():
        raise RuntimeError(
            f"Missing greeting asset for provider {provider!r}: {path}. "
            f"Run `python scripts/generate_greeting.py {provider}` to generate it."
        )
    return path.read_bytes()


@contextmanager
def timed(label: str):
    start = time.perf_counter()
    yield
    print(f"[timing] {label}: {time.perf_counter() - start:.2f}s")


def _apologize_and_end_call(e: QuotaExceededError, trigger) -> None:
    print(f"[quota] {e}")
    message = f"Sorry, I've hit my usage quota for {e.provider}. Please try again later. Goodbye."
    try:
        audio_io.play_with_comfort_noise(lambda: tts.synthesize_stream(message), tts.PCM_SAMPLE_RATE, trigger)
    except QuotaExceededError:
        print("[quota] couldn't speak the apology either -- TTS quota is also exhausted")


def _apologize_and_continue(e: ModelOverloadedError, trigger) -> None:
    print(f"[overloaded] {e}")
    message = f"Sorry, the {e.provider} model is temporarily overloaded. Please try asking again in a moment."
    try:
        audio_io.play_with_comfort_noise(lambda: tts.synthesize_stream(message), tts.PCM_SAMPLE_RATE, trigger)
    except QuotaExceededError:
        print("[overloaded] couldn't speak the apology either -- TTS quota is also exhausted")


def handle_call(trigger, greeting_audio: bytes) -> None:
    conversation = Conversation()
    with timed("greeting playback"):
        audio_io.play_pcm_stream([greeting_audio], tts.PCM_SAMPLE_RATE, trigger)

    while not trigger.is_hung_up():
        with timed("record (includes caller's speaking time)"):
            samples = audio_io.record_until_silence(trigger)

        if trigger.poll_hung_up():
            break

        wav_bytes = audio_io.audio_to_wav_bytes(samples)
        result = {"heard": None, "reply": None}

        def produce():
            with timed("stt"):
                result["heard"] = stt.transcribe(wav_bytes)
            if not result["heard"] or trigger.poll_hung_up():
                return
            with timed("llm"):
                result["reply"] = conversation.ask(result["heard"])
            if trigger.poll_hung_up():
                return
            with timed("tts:synthesize"):
                yield from tts.synthesize_stream(result["reply"])

        try:
            with timed("reply (wait+playback)"):
                audio_io.play_with_comfort_noise(produce, tts.PCM_SAMPLE_RATE, trigger)
        except QuotaExceededError as e:
            _apologize_and_end_call(e, trigger)
            break
        except ModelOverloadedError as e:
            _apologize_and_continue(e, trigger)
            continue

        heard = result["heard"]
        if not heard:
            continue
        print(f"You said: {heard}")

        reply = result["reply"]
        if reply is None:
            break
        print(f"{config.LLM_PROVIDER}: {reply}")

    print("Call ended.\n")


def main() -> None:
    trigger = get_trigger(config.PHONE_TRIGGER, config.HOOK_GPIO_PIN)
    greeting_audio = _load_greeting_audio(config.LLM_PROVIDER)
    with timed("warmup"):
        tts.warm_up()
        if config.STT_PROVIDER == "openai":
            stt.warm_up()
    print(f"Ready. Using '{config.PHONE_TRIGGER}' trigger.")
    while True:
        trigger.wait_for_pickup()
        handle_call(trigger, greeting_audio)


if __name__ == "__main__":
    main()
