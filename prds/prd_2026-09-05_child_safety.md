# PRD: G-rated, child-safe spoken replies

## Objective

Make every spoken reply G-rated and safe for a child of any age to hear, no matter what the caller asks -- via two layers: a system prompt that instructs the model to always answer in a kid-friendly, G-rated way and gently deflect inappropriate topics, plus a hard technical backstop that checks every generated reply against OpenAI's moderation API before it's spoken, substituting a canned safe line if the reply is flagged or if the check itself fails.

## Context

This phone can be picked up and used by a child of any age, and the caller can ask anything. Today `config.SYSTEM_PROMPT` (`claude_phone/config.py`) only shapes tone/length for being spoken aloud -- it says nothing about content appropriateness -- and there is no technical check on what the LLM generates before `Conversation.ask()` (`claude_phone/assistant.py`) hands it to TTS. Both `_ask_claude` and `_ask_gemini` already use the same `config.SYSTEM_PROMPT` as their system instruction, so a prompt change covers both providers with one edit.

**Caveat that shapes this design:** OpenAI's moderation API detects clearly unsafe categories (sexual content, hate, graphic violence, self-harm, etc.) -- it is not a general "G-rating" detector and won't catch things like mild profanity or a callous-but-not-flagged tone. The system prompt is therefore the primary mechanism for the *G-rated feel* of every answer; the moderation call is a backstop against worst-case content actually reaching the child, not a guarantee of Disney-movie tone on every line.

## Requirements

1. The system prompt instructs the model to always give G-rated answers (no profanity, sexual content, graphic violence, or other mature themes) and, when a caller asks about something inappropriate or sensitive, to briefly and kindly redirect (e.g. suggest asking a parent) rather than refuse at length or lecture.
2. The system prompt must not make the assistant over-refuse: factual questions that merely touch on serious topics in an age-appropriate way (e.g. why dinosaurs went extinct, how predators hunt) should still get normal, straightforward answers.
3. Every LLM-generated reply is checked against OpenAI's moderation API before it is spoken. If flagged, the reply is replaced with a configurable canned fallback line before being spoken or stored in conversation history.
4. If the moderation check itself fails for any reason (network error, rate limit, malformed response), the reply is treated as unsafe and replaced with the same fallback line -- fail-safe, not fail-open.
5. A moderation-check failure or a flagged reply must not end the call or raise a user-visible error the way `QuotaExceededError`/`ModelOverloadedError` do -- it silently substitutes the fallback and the call continues normally.
6. Conversation history stores what was actually spoken (the substituted fallback when applicable), not the original flagged/unverified reply, so later turns in the same call don't reference content that was never actually said.
7. The moderation backstop runs regardless of `LLM_PROVIDER` (claude or gemini).
8. The moderation backstop can be turned off via a config flag, restoring today's exact behavior (no moderation call, no added latency).
9. No changes to the audio/call-flow pipeline (`main.py`'s `handle_call`, `audio_io.py`) are required -- the added latency of the moderation call is naturally covered by the existing comfort-noise wait indicator, since it happens inside `Conversation.ask()` before a plain string is returned.

## Acceptance Criteria

- Asking a harmless factual question (e.g. "why did the dinosaurs go extinct?", "how do lions hunt?") gets a normal, unhedged factual answer -- no refusal, no disclaimer.
- Asking something deliberately adult/inappropriate gets a brief, warm redirect ("that's a good one to ask a grown-up... what else can I help with?") rather than the actual content or a lecture.
- Calling `safety.is_child_safe(...)` directly with obviously unsafe text returns `False`; with benign text returns `True`.
- Setting `CHILD_SAFETY_ENABLED=false` and restarting restores today's exact behavior: no `[safety]`-prefixed log lines, no moderation warm-up, no added latency.
- A simulated moderation-check failure (e.g. bad API key or forced exception) results in the fallback line being spoken and the call continuing normally -- it does not crash or end the call.
- Reply/greeting audio and the rest of the call (recording, STT, hangup handling, comfort noise) are unaffected by this change.

## Design

- `config.py`: add, near `SYSTEM_PROMPT`, following the `COMFORT_NOISE_*` naming/parsing convention:
  ```python
  CHILD_SAFETY_ENABLED = os.environ.get("CHILD_SAFETY_ENABLED", "true").lower() != "false"
  CHILD_SAFETY_FALLBACK_REPLY = os.environ.get(
      "CHILD_SAFETY_FALLBACK_REPLY",
      "Let's talk about something else -- what else are you curious about?",
  )
  ```

- `config.py`: rewrite `SYSTEM_PROMPT` to keep the existing spoken-aloud/length constraints and add child-safety framing:
  ```python
  SYSTEM_PROMPT = (
      "You are the voice on the other end of a phone call. Keep replies short, "
      "conversational, and natural to hear spoken aloud -- a sentence or two "
      "unless the caller clearly wants more detail. No markdown, lists, or "
      "headers, since this is read aloud, not read on screen.\n\n"
      "This phone can be answered by a child of any age, so every reply must be "
      "G-rated: no profanity, sexual content, graphic violence, or other mature "
      "themes. If a caller asks about something inappropriate or sensitive for a "
      "child (e.g. violence, drugs, sexual topics, self-harm), don't lecture or "
      "refuse at length -- briefly and kindly steer away from it, for example by "
      "suggesting they ask a parent or grown-up about that one, then offer to "
      "help with something else. Stay warm and friendly, like a favorite aunt or "
      "uncle, not a disclaimer machine. This doesn't mean avoiding real topics "
      "that merely touch on serious subjects in a factual, age-appropriate way -- "
      "questions like why dinosaurs went extinct, how predators hunt, or how "
      "volcanoes erupt should still get normal, straightforward answers. The bar "
      "is G-rated content, not avoiding every topic that isn't strictly cheerful."
  )
  ```

- New module `claude_phone/safety.py`, following the `tts.py`/`stt.py` OpenAI-client + `warm_up()` pattern exactly (own module because it must run identically regardless of `LLM_PROVIDER`). Deliberately does **not** raise `QuotaExceededError` on failure the way `tts.py`/`stt.py` do -- a moderation-check failure should swap in the fallback line and let the call continue, not end it:
  ```python
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
  ```

- `assistant.py`: add `from . import safety` to imports; modify `Conversation.ask()`:
  ```python
  def ask(self, text: str) -> str:
      self._messages.append({"role": "user", "content": text})
      reply = self._ask(self._messages)
      if config.CHILD_SAFETY_ENABLED and not safety.is_child_safe(reply):
          reply = config.CHILD_SAFETY_FALLBACK_REPLY
      self._messages.append({"role": "assistant", "content": reply})
      return reply
  ```
  The (possibly substituted) reply is what gets appended to history, so it always reflects what was actually spoken.

- `main.py`: add `safety` to the import line (`from . import audio_io, config, safety, stt, tts`). In `main()`, alongside the existing warmup calls:
  ```python
  with timed("warmup"):
      tts.warm_up()
      if config.STT_PROVIDER == "openai":
          stt.warm_up()
      if config.CHILD_SAFETY_ENABLED:
          safety.warm_up()
  ```
  `handle_call` itself needs no changes -- `produce()` already just calls `conversation.ask(heard)` inside `with timed("llm")` and gets back a plain `str` either way; no new exception type escapes `Conversation.ask()`. The moderation round-trip is additional latency inside the existing "llm" timing stage, already covered by the comfort-noise wait indicator.

- `requirements.txt`: currently unpinned (`openai`). Add a floor to guarantee `.moderations.create()` / `omni-moderation-latest` are available on a fresh install: change `openai` to `openai>=1.47.0`.

## Tasks

1. Add `CHILD_SAFETY_ENABLED` and `CHILD_SAFETY_FALLBACK_REPLY` to `config.py`, and rewrite `SYSTEM_PROMPT`.
2. Write `claude_phone/safety.py` (`warm_up()` + `is_child_safe()`).
3. Update `Conversation.ask()` in `assistant.py` to call `safety.is_child_safe()` and substitute the fallback when needed.
4. Wire `safety.warm_up()` into `main()`'s existing warmup block, gated on `config.CHILD_SAFETY_ENABLED`.
5. Add a version floor to `requirements.txt`.
6. Update `README.md`'s Configuration table with `CHILD_SAFETY_ENABLED` / `CHILD_SAFETY_FALLBACK_REPLY` rows, following the existing convention (see the `COMFORT_NOISE_*` rows).
7. Manually test: harmless factual questions still get full answers, a deliberately inappropriate question gets a system-prompt deflection, `safety.is_child_safe()` returns the right bool for obviously flagged vs. benign text via a REPL check, a simulated moderation failure falls back safely without ending the call, and `CHILD_SAFETY_ENABLED=false` restores today's exact behavior.

## Deployment steps

- Pure code change -- no new assets. `requirements.txt` gains a version floor on an already-installed dependency (`openai`), so `pip install -r requirements.txt` may need to run again if the installed version is older than `1.47.0` (unlikely; the currently installed version is `2.45.0`).
- Pull latest code, reinstall requirements if needed, and restart the `claude-phone` service.
- No new env vars are required to deploy -- both new config values have safe defaults (`CHILD_SAFETY_ENABLED=true`).
- If the fallback line needs to sound different, or the moderation backstop needs to be disabled for debugging, set `CHILD_SAFETY_FALLBACK_REPLY` / `CHILD_SAFETY_ENABLED` in `.env` and restart.
