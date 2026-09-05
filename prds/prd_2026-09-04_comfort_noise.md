# PRD: Comfort noise during reply wait

## Objective

Replace dead air with a quiet R2D2-style stream of beeps and chirps that plays through the speaker for the entire time the caller is waiting for the app's voice to come back -- from the moment they stop talking until the first byte of the app's reply (or apology) audio is ready to play. Signals "the line is still live" instead of silence that can read as a dropped call.

(Sound design note: the original draft of this PRD called for a looping ambient tone. After A/B-listening to several procedurally generated candidates -- phone-line hiss, a periodic chime, a warm ambient pad, and R2D2-style chirps -- the R2D2 direction was picked instead, then further tuned to be softer and slower-paced, then changed from a fixed repeating loop to a continuously-randomized, never-repeating chirp stream. The requirements and design below reflect that final direction.)

## Context

In `handle_call` (`claude_phone/main.py`), after `record_until_silence` returns, the caller hears nothing while `stt.transcribe`, `conversation.ask`, and the time-to-first-byte of `tts.synthesize_stream` all run sequentially and block on network I/O (see the `[timing] stt`, `[timing] llm`, `[timing] tts:reply+playback` log lines). The same dead-air gap exists in `_apologize_and_end_call` and `_apologize_and_continue`, which also call `tts.synthesize_stream` and wait for the first chunk before any sound plays. There's currently no audio output at all during any of these waits.

## Requirements

1. As soon as the caller's turn ends (recording stops) and the app begins working on a reply, a quiet R2D2-style chirp stream starts playing through the speaker.
2. The chirps are procedurally generated in code (no audio asset file, no TTS/API call). Pitch, duration, and spacing are randomized within tuned ranges on every chirp, grouped into short phrases with a longer pause between them, so a long wait never sounds like a fixed clip repeating. Every chirp fades in/out to silence, so there's never an audible click or pop.
3. The moment the app's real reply/apology audio has its first chunk ready, comfort noise stops and reply audio begins immediately, with no perceptible gap or overlap between the two.
4. Comfort noise also covers the STT step (not just the LLM and TTS legs) -- it plays continuously across all three stages as one uninterrupted sound, not three separate starts/stops.
5. If STT hears nothing (empty transcription), comfort noise stops (since no reply is coming) and the call returns to listening, exactly like today minus the added sound.
6. If the caller hangs up while comfort noise is playing, it stops promptly (within about one chunk, ~100ms) and the call ends the same way it does today.
7. Comfort noise also plays during the `_apologize_and_end_call` (quota exceeded) and `_apologize_and_continue` (model overloaded) waits, using the same mechanism.
8. Comfort noise is clearly quieter than spoken reply audio, and is scaled by the existing master `config.OUTPUT_VOLUME` the same way reply/greeting audio is.
9. The feature can be turned off via a config flag, fully restoring today's silent-wait behavior.
10. No new third-party dependencies -- built with `numpy`, already used in `audio_io.py`.

## Acceptance Criteria

- Speaking to the app and waiting for a reply: silence is replaced by soft R2D2-style chirps from the instant you stop talking until the reply starts speaking; no click or pop is ever audible between chirps.
- Waiting through more than one chirp phrase (e.g. a slow LLM response) doesn't sound like a clip looping -- the chirp pitches/timing keep varying.
- The transition from comfort noise to reply speech has no dead gap and no overlap -- it sounds like one continuous stream of audio.
- Asking something the STT fails to transcribe: comfort noise plays during the STT attempt, then stops and the app goes back to listening once it's clear nothing was heard -- no reply is ever spoken.
- Hanging up while comfort noise is playing ends the call promptly, same as hanging up during any other playback today.
- Triggering the quota-exceeded or model-overloaded paths: comfort noise plays while the apology message is being synthesized, then the apology plays normally.
- Setting `COMFORT_NOISE_ENABLED=false`: behavior is byte-for-byte what it is today (silence during all the same waits).
- Reply audio and greeting audio are not perceptibly changed in volume or quality by this change.

## Design

- `config.py`: add
  ```python
  COMFORT_NOISE_ENABLED = os.environ.get("COMFORT_NOISE_ENABLED", "true").lower() != "false"
  COMFORT_NOISE_VOLUME = float(os.environ.get("COMFORT_NOISE_VOLUME", "0.11"))  # relative to full-scale, before OUTPUT_VOLUME
  ```

- New module `claude_phone/comfort_noise.py`:
  - Tuned constant ranges for chirp pitch (`FREQ_LO_HZ`/`FREQ_HI_HZ`, e.g. 320-2700 Hz), chirp duration (`CHIRP_DUR_LO_S`/`CHIRP_DUR_HI_S`), the silent gap after each chirp (`GAP_LO_S`/`GAP_HI_S`), how many chirps make up one "phrase" (`PHRASE_CHIRPS_LO`/`PHRASE_CHIRPS_HI`), and the longer silent pause between phrases (`PHRASE_PAUSE_LO_S`/`PHRASE_PAUSE_HI_S`).
  - `_make_chirp(samplerate, start_hz, end_hz, duration_s) -> np.ndarray`: builds one pitched sweep (exponential frequency interpolation from `start_hz` to `end_hz`) with a touch of 3rd-harmonic "buzz" for a synth-droid timbre, and a short (~5ms) linear fade in/out so it starts and ends at zero amplitude -- the reason nothing needs crossfading to stay click-free.
  - `_sample_stream(rng, samplerate) -> Iterator[np.ndarray]`: an infinite generator that, forever, picks a random phrase length, yields that many `(chirp, silent gap)` pairs with freshly randomized pitch/duration/gap each time, then yields one longer silent pause before starting the next phrase. Never repeats the same sequence.
  - `loop_chunks(samplerate: int, chunk_ms: int = 100) -> Iterator[bytes]`: creates its own unseeded `np.random.default_rng()` (so every call -- i.e. every wait during the call -- gets its own fresh, never-repeating sequence), buffers `_sample_stream`'s variable-length pieces, and yields fixed `chunk_ms` int16 PCM byte slices, scaled by `config.COMFORT_NOISE_VOLUME`.

- `audio_io.py`:
  - Extract the existing per-chunk volume-scaling logic in `play_pcm_stream` into a small `_scale_volume(chunk: bytes) -> bytes` helper so it can be reused.
  - Add:
    ```python
    def play_with_comfort_noise(produce_chunks: Callable[[], Iterable[bytes]], samplerate: int, trigger) -> None:
        """Runs `produce_chunks` on a background thread. Until it yields its first chunk,
        plays quiet comfort noise instead of dead air; once real chunks start arriving,
        plays those instead, with no gap. Any exception raised inside `produce_chunks` is
        re-raised here after the background thread finishes producing (or is abandoned, if
        the call was hung up first). Stops immediately, whether mid-comfort-noise or
        mid-reply, if `trigger` reports a hangup.

        If `config.COMFORT_NOISE_ENABLED` is false, just runs `produce_chunks`
        synchronously through `play_pcm_stream`, preserving the original silent-wait
        behavior exactly.
        """
    ```
    Implementation shape: a `queue.Queue` fed by a daemon worker thread that iterates `produce_chunks()` and puts each chunk (or a sentinel for completion, or a wrapped exception) onto the queue. The main thread opens one `sd.RawOutputStream` for the whole call (comfort noise + reply, back to back, so there's no device re-open click between them) and loops: poll the queue non-blocking; if empty, write the next 100ms comfort-noise chunk and continue; once a real chunk arrives, stop pulling from the comfort-noise generator and drain the queue (blocking, with periodic hangup polling) until the completion sentinel; if the worker's exception sentinel arrives, raise it in the main thread. Every chunk written goes through `_scale_volume`.

- `main.py`:
  - `handle_call`: replace the sequential `stt` / `llm` / `tts:reply+playback` block with a single producer function passed to `audio_io.play_with_comfort_noise`. The producer runs the existing three stages (still individually wrapped in `timed(...)`) and records `heard` / `reply` into a small mutable result holder (e.g. a dict created in `handle_call`'s scope) since it runs on a background thread and can't just `return` multiple values through the call site:
    ```python
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
        yield from tts.synthesize_stream(result["reply"])

    audio_io.play_with_comfort_noise(produce, tts.PCM_SAMPLE_RATE, trigger)
    ```
    followed by the existing `if not heard: continue`, print, and hangup-check logic, now reading from `result` instead of local variables. `QuotaExceededError` / `ModelOverloadedError` raised inside `produce` propagate out of `play_with_comfort_noise` and are caught by the existing `except` clauses in `handle_call`, unchanged.
  - `_apologize_and_end_call` / `_apologize_and_continue`: replace their direct `audio_io.play_pcm_stream(tts.synthesize_stream(message), ...)` calls with `audio_io.play_with_comfort_noise(lambda: tts.synthesize_stream(message), tts.PCM_SAMPLE_RATE, trigger)`.

## Tasks

1. Add `COMFORT_NOISE_ENABLED` and `COMFORT_NOISE_VOLUME` to `config.py`.
2. Write `claude_phone/comfort_noise.py` (randomized chirp-stream generation + chunked iterator).
3. Add `audio_io.play_with_comfort_noise`, extracting the shared `_scale_volume` helper from `play_pcm_stream`.
4. Refactor `handle_call`'s reply pipeline in `main.py` into the `produce()`-closure shape described above, wired through `play_with_comfort_noise`.
5. Wrap the `tts.synthesize_stream` calls in `_apologize_and_end_call` and `_apologize_and_continue` the same way.
6. Manually test: normal reply flow (chirps audible, no clicks, clean handoff to reply), a slow reply spanning multiple chirp phrases (confirms it doesn't sound like a repeating loop), empty-STT path (chirps stop, no reply, back to listening), hangup mid-wait, both apology paths, and `COMFORT_NOISE_ENABLED=false` restoring silent waits exactly.

## Deployment steps

- Pure code change -- no new assets, no new dependencies, no env vars required (both new config values have defaults).
- Pull latest code and restart the `claude-phone` service.
- If the comfort noise is too loud/quiet or the chirp character needs adjusting after listening in production, tune `COMFORT_NOISE_VOLUME` (env var) or the frequency/duration/gap ranges in `comfort_noise.py` and restart -- no regeneration step needed since it's synthesized at runtime.
