import time
from contextlib import contextmanager

from . import audio_io, config, stt, tts
from .assistant import Conversation
from .trigger import get_trigger

GREETING = "Hello?"


@contextmanager
def timed(label: str):
    start = time.perf_counter()
    yield
    print(f"[timing] {label}: {time.perf_counter() - start:.2f}s")


def handle_call(trigger) -> None:
    conversation = Conversation()
    with timed("tts:greeting"):
        greeting_audio = tts.synthesize(GREETING)
    with timed("playback:greeting"):
        audio_io.play_audio(greeting_audio)

    while not trigger.is_hung_up():
        with timed("record (includes caller's speaking time)"):
            samples = audio_io.record_until_silence()
        wav_bytes = audio_io.audio_to_wav_bytes(samples)

        with timed("stt"):
            heard = stt.transcribe(wav_bytes)
        if not heard:
            continue
        print(f"You said: {heard}")

        with timed("llm"):
            reply = conversation.ask(heard)
        print(f"{config.LLM_PROVIDER}: {reply}")

        with timed("tts:reply"):
            reply_audio = tts.synthesize(reply)
        with timed("playback:reply"):
            audio_io.play_audio(reply_audio)

    print("Call ended.\n")


def main() -> None:
    trigger = get_trigger(config.PHONE_TRIGGER, config.HOOK_GPIO_PIN)
    print(f"Ready. Using '{config.PHONE_TRIGGER}' trigger.")
    while True:
        trigger.wait_for_pickup()
        handle_call(trigger)


if __name__ == "__main__":
    main()
