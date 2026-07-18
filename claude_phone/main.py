from . import audio_io, config, stt, tts
from .assistant import Conversation
from .trigger import get_trigger

GREETING = "Hello?"


def handle_call(trigger) -> None:
    conversation = Conversation()
    audio_io.play_audio(tts.synthesize(GREETING))

    while not trigger.is_hung_up():
        samples = audio_io.record_until_silence()
        wav_bytes = audio_io.audio_to_wav_bytes(samples)

        heard = stt.transcribe(wav_bytes)
        if not heard:
            continue
        print(f"You said: {heard}")

        reply = conversation.ask(heard)
        print(f"{config.LLM_PROVIDER}: {reply}")

        audio_io.play_audio(tts.synthesize(reply))

    print("Call ended.\n")


def main() -> None:
    trigger = get_trigger(config.PHONE_TRIGGER, config.HOOK_GPIO_PIN)
    print(f"Ready. Using '{config.PHONE_TRIGGER}' trigger.")
    while True:
        trigger.wait_for_pickup()
        handle_call(trigger)


if __name__ == "__main__":
    main()
