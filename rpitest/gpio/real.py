"""Echte GPIO via libgpiod 2.x (python3-libgpiod op Raspberry Pi OS Trixie).

Bookworm levert libgpiod 1.x met een andere Python-API; dat werkt hier niet.
De module `gpiod` wordt pas bij gebruik geladen, zodat de rest van het pakket ook op
Windows importeerbaar blijft.
"""

from __future__ import annotations

import glob
from collections.abc import Iterable
from types import ModuleType

from .ports import PINS, GpioPort, Pull

# Labels van de gpiochip die de 40-pins header bedient. De chipnummers wisselen per
# model en kernelversie (Pi 5: gpiochip4, nieuwere kernels gpiochip0), het label niet.
# Nog te bevestigen op de echte Pi 4 en Pi 5: zie `python -m rpitest.agent --list-chips`.
HEADER_CHIP_LABELS = frozenset({"pinctrl-rp1", "pinctrl-bcm2711", "pinctrl-bcm2835"})
MIN_LINES = 28  # BCM 0..27


def load_gpiod() -> ModuleType:
    try:
        import gpiod
        import gpiod.line  # noqa: F401  (zorgt dat gpiod.line als attribuut bestaat)
    except ImportError as exc:
        raise RuntimeError("Python-module 'gpiod' ontbreekt: sudo apt install python3-libgpiod") from exc
    if not hasattr(gpiod, "request_lines"):
        raise RuntimeError(
            "gpiod 1.x gevonden; we hebben libgpiod 2.x nodig (Raspberry Pi OS Trixie, niet Bookworm)"
        )
    return gpiod


def list_chips(gpiod: ModuleType | None = None) -> list[tuple[str, str, int]]:
    """(pad, label, aantal lijnen) van alle gpiochips."""
    g = gpiod or load_gpiod()
    chips = []
    for path in sorted(glob.glob("/dev/gpiochip*")):
        try:
            with g.Chip(path) as chip:
                info = chip.get_info()
                chips.append((path, info.label, info.num_lines))
        except OSError:
            continue
    return chips


def find_header_chip(gpiod: ModuleType | None = None) -> str:
    chips = list_chips(gpiod)
    for path, label, num_lines in chips:
        if label in HEADER_CHIP_LABELS and num_lines >= MIN_LINES:
            return path
    found = ", ".join(f"{p} ({label}, {n} lijnen)" for p, label, n in chips) or "geen"
    raise RuntimeError(f"GPIO-chip van de header niet gevonden. Gevonden chips: {found}")


class GpiodPort(GpioPort):
    """Beheert alle PINS via één line request. Elke wijziging past de volledige
    configuratie toe, zodat er nooit onduidelijkheid is over de toestand van overige lijnen."""

    def __init__(self, chip_path: str | None = None, pins: Iterable[int] = PINS,
                 gpiod: ModuleType | None = None):
        self._g = gpiod or load_gpiod()
        self._pins = tuple(pins)
        self._path = chip_path or find_header_chip(self._g)
        self._settings = {p: self._input_settings(Pull.NONE) for p in self._pins}
        self._request = self._open()

    @property
    def chip_path(self) -> str:
        return self._path

    def _input_settings(self, pull: str):
        line = self._g.line
        if pull not in Pull.ALL:
            raise ValueError(f"onbekende pull: {pull!r}")
        bias = {Pull.NONE: line.Bias.DISABLED, Pull.UP: line.Bias.PULL_UP, Pull.DOWN: line.Bias.PULL_DOWN}[pull]
        return self._g.LineSettings(direction=line.Direction.INPUT, bias=bias)

    def _open(self):
        try:
            return self._g.request_lines(self._path, consumer="rpitest", config=dict(self._settings))
        except OSError as exc:
            raise RuntimeError(self._open_error(exc)) from exc

    def _open_error(self, exc: OSError) -> str:
        busy = []
        for pin in self._pins:  # zoek welke lijnen bezet zijn om een bruikbare melding te geven
            try:
                self._g.request_lines(self._path, consumer="rpitest-probe",
                                      config={pin: self._input_settings(Pull.NONE)}).release()
            except OSError:
                busy.append(pin)
        if busy:
            return (f"GPIO-lijnen in gebruik door een ander proces of een driver: "
                    f"{', '.join(map(str, busy))} (draait er al een rpitest, of staan I2C/SPI/UART-overlays aan?)")
        return f"GPIO-lijnen aanvragen op {self._path} mislukt: {exc}"

    def _apply(self) -> None:
        self._request.reconfigure_lines(dict(self._settings))

    def _check(self, pins: Iterable[int]) -> list[int]:
        pins = list(pins)
        unknown = [p for p in pins if p not in self._settings]
        if unknown:
            raise ValueError(f"pin(nen) niet beheerd: {unknown}")
        return pins

    def set_input(self, pins: Iterable[int], pull: str) -> None:
        settings = self._input_settings(pull)
        for p in self._check(pins):
            self._settings[p] = settings
        self._apply()

    def drive(self, pin: int, value: int) -> None:
        if value not in (0, 1):
            raise ValueError("value moet 0 of 1 zijn")
        (pin,) = self._check([pin])
        line = self._g.line
        self._settings[pin] = self._g.LineSettings(
            direction=line.Direction.OUTPUT,
            output_value=line.Value.ACTIVE if value else line.Value.INACTIVE,
        )
        self._apply()

    def read(self, pins: Iterable[int]) -> dict[int, int]:
        pins = self._check(pins)
        values = self._request.get_values(pins)
        return {p: int(v == self._g.line.Value.ACTIVE) for p, v in zip(pins, values)}

    def close(self) -> None:
        if self._request is not None:
            self._request.release()  # lijnen vallen terug naar hun standaardtoestand
            self._request = None

    def __enter__(self) -> GpiodPort:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
