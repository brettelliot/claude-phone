# claude-phone

Turn an old landline handset into a voice interface for Claude. Pick up the
handset, talk, and Claude talks back — powered by a Raspberry Pi, the
Anthropic API, and speech-to-text/text-to-speech.

## How it works

`claude_phone/main.py` runs a simple loop:

1. Wait for the phone to be picked up (hook switch, or Enter key for testing).
2. Play a greeting through the earpiece.
3. Record until the caller stops talking (silence detection), transcribe it
   (`stt.py`, via Wispr Flow or OpenAI Whisper), send it to Claude
   (`assistant.py`, keeping the conversation history for the call), and speak
   the reply back (`tts.py`, via OpenAI TTS).
4. Repeat until the handset goes back on the hook, then reset the
   conversation for the next call.

The pickup/hangup detection is abstracted behind `trigger.py` so you can
develop entirely on a laptop (`PHONE_TRIGGER=keyboard`) before wiring up real
hardware (`PHONE_TRIGGER=gpio`).

## Parts list

- Raspberry Pi (3B+, 4, or Zero 2 W all work) + power supply + microSD card
- An old landline handset with its hook switch (either a full phone body, or
  just a handset + cradle/switch assembly)
- USB sound card / audio adapter with a mic-in and headphone-out (the Pi has
  no built-in mic input, so this is required)
- Multimeter, for identifying the handset's wire pairs
- Jumper wires (female-to-female, or male-to-female) for the hook switch
- Soldering iron, solder, heat shrink
- Small enclosure or perfboard to mount the Pi and wiring inside/behind the
  phone (optional, but recommended once it's working)

## Hardware build

### Wiring the handset to the USB sound card

Old handsets connect via a 4-wire cable (usually an RJ9/RJ22 modular plug):
one pair for the earpiece (receiver) and one pair for the microphone
(transmitter). Cut the cable and use a multimeter's continuity/resistance
mode to tell the pairs apart — the mic pair is typically much higher
resistance than the earpiece pair.

- Solder the earpiece pair to a 3.5mm TRS plug and connect it to the sound
  card's headphone/speaker-out jack.
- Solder the mic pair to a 3.5mm TRS plug and connect it to the sound card's
  mic-in jack.

Most electret handset mics work fine off the small bias voltage a USB sound
card's mic input provides. If your handset has an old carbon-granule
microphone (common on very old rotary phones) it won't work directly off a
sound card mic input and will need a bias/amplifier circuit — swapping in a
modern electret capsule is usually simpler.

Once connected, list audio devices from the Pi to get the exact names/indices:

```bash
python -m sounddevice
```

Set `INPUT_DEVICE` / `OUTPUT_DEVICE` in `.env` if the sound card isn't picked
up as the system default (see Configuration below).

### Wiring the hook switch

The hook switch is just a mechanical switch that opens or closes when the
handset is lifted. Wire one leg to a GPIO pin and the other to any ground pin
on the Pi's header — the code uses gpiozero's internal pull-up
(`Button(pin, pull_up=True)`), so no external resistor is needed.

- Signal leg → GPIO17 (BCM numbering, physical pin 11) by default, or
  whichever pin you set as `HOOK_GPIO_PIN`
- Other leg → any GND pin (e.g. physical pin 9)

`gpiozero`'s `Button.is_pressed` is `True` when the switch contact is closed.
`trigger.py` assumes closed == handset lifted. Old phones vary in which state
the switch is in when on-hook vs. off-hook, so test it: run with
`PHONE_TRIGGER=gpio`, watch the logs while lifting/hanging up the handset,
and if pickup/hangup are backwards, swap the assumption in
`GPIOTrigger.is_hung_up()` (`claude_phone/trigger.py`).

## Setting up the Pi

1. Flash Raspberry Pi OS (Lite is fine — this runs headless) with the
   Raspberry Pi Imager. In the imager's settings, enable SSH and configure
   Wi-Fi so you can connect without a monitor.
2. SSH in and install system dependencies:

   ```bash
   sudo apt update
   sudo apt install -y python3-venv python3-pip portaudio19-dev libsndfile1
   ```

   (`portaudio19-dev` is required for `sounddevice`; `libsndfile1` for
   `soundfile`.)
3. Clone the repo and set up a virtualenv:

   ```bash
   git clone <this-repo-url> claude-phone
   cd claude-phone
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. Copy the env file and fill in your keys:

   ```bash
   cp .env.example .env
   ```
5. Plug in the USB sound card and run `python -m sounddevice` to confirm it's
   detected, setting `INPUT_DEVICE`/`OUTPUT_DEVICE` in `.env` if needed.
6. Test the software first with `PHONE_TRIGGER=keyboard` (no hardware wiring
   required — see Running below) before wiring up the hook switch.
7. Once the hook switch is wired, set `PHONE_TRIGGER=gpio` in `.env` and test
   with the real handset.

## Configuration

All configuration is via environment variables, loaded from `.env`
(`claude_phone/config.py`). See `.env.example` for the full list with
defaults; the notable ones:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required. Used for Claude replies. |
| `OPENAI_API_KEY` | Required. Used for TTS, and STT if `STT_PROVIDER=openai`. |
| `STT_PROVIDER` | `wispr` (default) or `openai`. |
| `WISPR_FLOW_API_KEY` | Required if `STT_PROVIDER=wispr`. Get one at https://platform.wisprflow.ai/. |
| `PHONE_TRIGGER` | `keyboard` (default, for development) or `gpio` (real hook switch). |
| `HOOK_GPIO_PIN` | BCM pin number for the hook switch. Default `17`. |
| `INPUT_DEVICE` / `OUTPUT_DEVICE` | Override the audio device used, if not the system default. |
| `CLAUDE_MODEL` | Defaults to `claude-sonnet-5`. |
| `TTS_MODEL` / `TTS_VOICE` | OpenAI TTS model/voice. Defaults `tts-1` / `alloy`. |
| `SILENCE_THRESHOLD` / `SILENCE_DURATION` | Tune end-of-speech detection sensitivity. |
| `MAX_RECORDING_SECONDS` | Hard cap on a single turn's recording length. |

## Running

```bash
source venv/bin/activate
python -m claude_phone.main
```

With `PHONE_TRIGGER=keyboard`, press Enter to "pick up," talk, press Enter
between turns, and type `hangup` to end the call. With `PHONE_TRIGGER=gpio`,
it just waits for the real handset.

## Running on boot

To have the phone come alive automatically when the Pi powers on, add a
systemd service:

```ini
# /etc/systemd/system/claude-phone.service
[Unit]
Description=claude-phone
After=network-online.target sound.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/pi/claude-phone
ExecStart=/home/pi/claude-phone/venv/bin/python -m claude_phone.main
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl enable --now claude-phone
journalctl -u claude-phone -f   # to watch logs
```

## Troubleshooting

- **No audio devices found / wrong device picked**: run
  `python -m sounddevice` to list devices and their indices/names, and set
  `INPUT_DEVICE`/`OUTPUT_DEVICE` in `.env` explicitly.
- **Pickup/hangup logic seems inverted**: see "Wiring the hook switch" above
  — flip the assumption in `GPIOTrigger.is_hung_up()`.
- **`WISPR_FLOW_API_KEY is not set` error**: either set it, or switch
  `STT_PROVIDER=openai` to use Whisper instead.
