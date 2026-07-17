"""Pickup/hangup detection.

Abstracted so the real hook switch (GPIO) can be swapped in later without
touching the rest of the app. Select with the PHONE_TRIGGER env var.
"""

from abc import ABC, abstractmethod


class Trigger(ABC):
    @abstractmethod
    def wait_for_pickup(self) -> None:
        """Block until the phone is picked up."""

    @abstractmethod
    def is_hung_up(self) -> bool:
        """Non-blocking check: has the phone been hung up right now?"""


class KeyboardTrigger(Trigger):
    """Stand-in for the hook switch: press Enter to pick up, Enter again to hang up."""

    def __init__(self):
        self._on_call = False

    def wait_for_pickup(self) -> None:
        input("\n[phone on hook] Press Enter to pick up...")
        self._on_call = True

    def is_hung_up(self) -> bool:
        if not self._on_call:
            return True
        # Hang up is checked between turns, not asynchronously, so we ask here.
        answer = input("[on call] Press Enter to keep talking, or type 'hangup': ").strip().lower()
        if answer == "hangup":
            self._on_call = False
            return True
        return False


class GPIOTrigger(Trigger):
    """Real hook switch on a Raspberry Pi via gpiozero.

    Wire the hook switch so the pin reads HIGH (pressed_up -> True) when the
    handset is ON the hook, and LOW when lifted, or adjust `pull_up`/logic to
    match your wiring.
    """

    def __init__(self, pin: int):
        from gpiozero import Button

        # Button.is_pressed == True means the switch contact is closed.
        # Assumes closed == handset lifted; flip if your wiring is reversed.
        self._button = Button(pin, pull_up=True)

    def wait_for_pickup(self) -> None:
        self._button.wait_for_press()

    def is_hung_up(self) -> bool:
        return not self._button.is_pressed


def get_trigger(kind: str, gpio_pin: int) -> Trigger:
    if kind == "keyboard":
        return KeyboardTrigger()
    if kind == "gpio":
        return GPIOTrigger(gpio_pin)
    raise ValueError(f"Unknown PHONE_TRIGGER: {kind!r} (expected 'keyboard' or 'gpio')")
