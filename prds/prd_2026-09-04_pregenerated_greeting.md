# PRD: Pre-recorded, provider-aware greeting

## Objective

Replace the greeting's live, per-call TTS synthesis with a pre-recorded audio clip, so picking up the phone plays the greeting with no TTS network latency. The greeting text should also identify which model is answering ("Hi, this is Gemini. What's your question?" / "Hi, this is Claude. What's your question?") instead of the current generic "Hello?".

## Context

`main.py` currently defines `GREETING = "Hello?"` and calls `tts.synthesize_stream(GREETING)` fresh on every single call pickup. Since the text never changes, this repeatedly pays for the same OpenAI TTS round trip -- observed at ~4s in `[timing] tts:greeting+playback` -- before the caller hears anything, and the greeting also doesn't say which LLM is on the line.

## Requirements

1. Greeting text is provider-aware: one line per `LLM_PROVIDER` value ("claude" / "gemini"), each naming that model, e.g. "Hi, this is Gemini. What's your question?"
2. Greeting audio for each provider is generated ahead of time (not at call time, not at process startup) via a one-off script, and stored as a static asset file in the repo.
3. Asset format is raw PCM matching what `tts.synthesize_stream` already produces (mono 16-bit, `tts.PCM_SAMPLE_RATE`), so it can be handed directly to `audio_io.play_pcm_stream` with no transcoding.
4. At call pickup, the app plays the pre-recorded asset for the active `LLM_PROVIDER` instead of calling `tts.synthesize_stream` for the greeting. No TTS API call happens on the greeting path anymore.
5. A script regenerates the asset(s) on demand from current `config.TTS_MODEL` / `config.TTS_VOICE` / greeting text. Regeneration is manual -- run the script by hand after changing any of those. There is no automatic staleness detection.
6. If the greeting asset for the active `LLM_PROVIDER` is missing at startup, the app fails immediately with a clear message telling the operator to run the generator script. It must not silently fall back to live TTS synthesis, since that would reintroduce the exact latency this feature removes.
7. Everything after the greeting (the caller's turns) is unchanged -- replies continue to use live streamed TTS exactly as today.

## Acceptance Criteria

- With `LLM_PROVIDER=gemini`, picking up plays "Hi, this is Gemini. What's your question?" with no OpenAI TTS call in the `[timing]` logs for that step.
- With `LLM_PROVIDER=claude`, picking up plays "Hi, this is Claude. What's your question?" from its own asset.
- Greeting playback latency is a disk read plus playback start -- no network round trip.
- Running the generator script (re)creates the `.pcm` asset(s); the app picks up the new audio on next run with no other code changes.
- Starting the app when the active provider's greeting asset is missing fails fast with an actionable error, rather than falling back to live TTS or dying with an unrelated stack trace.
- The rest of a call (recording, STT, LLM reply, reply TTS, hangup handling) behaves exactly as it does today.

## Design

- `config.py`: add a `GREETINGS` dict keyed the same way as `assistant._PROVIDERS`, e.g.:
  ```python
  GREETINGS = {
      "claude": "Hi, this is Claude. What's your question?",
      "gemini": "Hi, this is Gemini. What's your question?",
  }
  ```
- New asset directory `assets/greetings/`, one file per provider: `assets/greetings/claude.pcm`, `assets/greetings/gemini.pcm`. Raw signed 16-bit little-endian mono PCM at `tts.PCM_SAMPLE_RATE` (24kHz) -- exactly the byte stream `tts.synthesize_stream` yields, concatenated. Small enough (a few hundred KB) to check into git, so a fresh checkout works without an API key or network call just to play the greeting.
- New script `scripts/generate_greeting.py`: for a given provider (or all providers in `config.GREETINGS` by default), looks up its greeting text, calls `tts.synthesize_stream(text)`, concatenates the chunks, and writes them to `assets/greetings/<provider>.pcm`. Prints what it wrote so it's obvious when to re-commit.
- `main.py` changes:
  - Remove the module-level `GREETING = "Hello?"` constant.
  - Add a loader (e.g. `_load_greeting_audio(provider: str) -> bytes`) that reads `assets/greetings/{provider}.pcm` and raises a `RuntimeError` naming the exact command to run (`python scripts/generate_greeting.py`) if the file is missing.
  - Load the active provider's greeting once, near the existing `tts.warm_up()` call in `main()`, and pass the bytes down into `handle_call`.
  - In `handle_call`, replace `tts.synthesize_stream(GREETING)` with the cached bytes, e.g. `audio_io.play_pcm_stream([greeting_audio], tts.PCM_SAMPLE_RATE, trigger)`.
  - Drop the `try/except QuotaExceededError` currently wrapping the greeting playback -- there's no API call left in that path to raise it.

## Tasks

1. Add `GREETINGS` dict to `config.py`.
2. Write `scripts/generate_greeting.py`.
3. Generate and commit `assets/greetings/claude.pcm` and `assets/greetings/gemini.pcm`.
4. Update `main.py`: drop the old `GREETING` constant and its live-synthesis call, add the asset loader with fail-fast missing-file handling, wire the cached bytes into `handle_call`.
5. Update `README.md` with a note to re-run the generator script (and commit the resulting asset) after changing greeting text, `TTS_VOICE`, or `TTS_MODEL`.
6. Manually test both providers end-to-end: pick up, confirm the correct greeting plays instantly, confirm the rest of the call is unaffected.

## Deployment steps

- Pull latest code -- the `.pcm` assets are committed, so no extra generation step is needed on a normal deploy.
- If greeting text, `TTS_VOICE`, or `TTS_MODEL` change, run `python scripts/generate_greeting.py` and commit the updated asset(s) *before* deploying.
- Restart the `claude-phone` service as usual; no env/config changes required unless a new provider is added (which also needs a new `GREETINGS` entry and a generated asset).
