"""Gesimuleerde TEST-SERVER + TEST-CLIENT met een kabel ertussen, inclusief foutinjectie.

Pin n van de ene Pi is verbonden met pin n van de andere. Fouten:
  stuck_low/stuck_high  pin hangt vast aan GND/3V3 (aan een kant)
  bridge                twee pinnen van een kant raken elkaar
  open                  de verbinding van pin n is onderbroken (kabel/soldeerpunt)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .ports import EXTERNAL_PULLUP, PINS, GpioPort, Pull

SERVER, CLIENT = "S", "C"
_OTHER = {SERVER: CLIENT, CLIENT: SERVER}
_FAULT_SHAPES = {"stuck_low": ("zijde", "pin"), "stuck_high": ("zijde", "pin"), "bridge": ("zijde", "pin", "pin"),
                 "open": ("pin",)}


def _describe(shape: tuple[str, ...]) -> str:
    return ":".join(f"<{part}>" for part in shape)


def _side(value) -> str:
    if value not in (SERVER, CLIENT):
        raise ValueError(f"onbekende zijde {value!r}: gebruik S (TEST-SERVER) of C (TEST-CLIENT)")
    return value


def _pin(value) -> int:
    try:
        pin = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{value!r} is geen pinnummer") from None
    if pin not in PINS:
        raise ValueError(f"GPIO{pin} bestaat niet op de testkabel: kies GPIO{PINS[0]} tot en met GPIO{PINS[-1]}")
    return pin


@dataclass
class _PinState:
    out: int | None = None  # None = input
    pull: str = Pull.NONE


class MockPort(GpioPort):
    def __init__(self, wiring: MockWiring, side: str):
        self._wiring = wiring
        self._side = side
        self._pins: dict[int, _PinState] = {}

    def state(self, pin: int) -> _PinState:
        return self._pins.setdefault(pin, _PinState())

    def set_input(self, pins: Iterable[int], pull: str) -> None:
        if pull not in Pull.ALL:
            raise ValueError(f"onbekende pull: {pull!r}")
        for p in pins:
            self._pins[p] = _PinState(out=None, pull=pull)

    def drive(self, pin: int, value: int) -> None:
        if value not in (0, 1):
            raise ValueError("value moet 0 of 1 zijn")
        self._pins[pin] = _PinState(out=value, pull=Pull.NONE)

    def read(self, pins: Iterable[int]) -> dict[int, int]:
        return {p: self._wiring.level(self._side, p) for p in pins}


class MockWiring:
    def __init__(self) -> None:
        self._ports = {SERVER: MockPort(self, SERVER), CLIENT: MockPort(self, CLIENT)}
        self._stuck: dict[tuple[str, int], int] = {}
        self._bridges: list[tuple[str, int, int]] = []
        self._opens: set[int] = set()
        # Momenten waarop twee uitgangen tegen elkaar in gingen: in een gezonde
        # opstelling mag dat nooit gebeuren (op echte hardware zou het stroom kosten).
        self.contention: list[tuple[str, int]] = []

    def port(self, side: str) -> MockPort:
        return self._ports[side]

    def add_fault(self, kind: str, *args) -> None:
        """Gooit ValueError met een duidelijke melding bij een onbekende fout, een verkeerd aantal argumenten,
        een onbekende zijde (S of C) of een pin buiten GPIO2 tot en met GPIO27."""
        shape = _FAULT_SHAPES.get(kind)
        if shape is None:
            raise ValueError(f"onbekende fout: {kind!r}")
        if len(args) != len(shape):
            raise ValueError(f"fout {kind!r} verwacht {_describe(shape)}, kreeg {len(args)} argument(en)")
        values = [_side(a) if part == "zijde" else _pin(a) for part, a in zip(shape, args, strict=True)]
        if kind == "stuck_low":
            self._stuck[(values[0], values[1])] = 0
        elif kind == "stuck_high":
            self._stuck[(values[0], values[1])] = 1
        elif kind == "bridge":
            if values[1] == values[2]:
                raise ValueError("fout 'bridge' verbindt twee verschillende pinnen")
            self._bridges.append((values[0], values[1], values[2]))
        else:
            self._opens.add(values[0])

    def _neighbours(self, side: str, pin: int):
        if pin not in self._opens:
            yield _OTHER[side], pin
        for s, a, b in self._bridges:
            if s == side and pin in (a, b):
                yield s, b if pin == a else a

    def _net(self, side: str, pin: int) -> set[tuple[str, int]]:
        seen = {(side, pin)}
        todo = [(side, pin)]
        while todo:
            for nb in self._neighbours(*todo.pop()):
                if nb not in seen:
                    seen.add(nb)
                    todo.append(nb)
        return seen

    def level(self, side: str, pin: int) -> int:
        net = self._net(side, pin)
        stuck = [self._stuck[n] for n in net if n in self._stuck]
        driven = [self._ports[s].state(p).out for s, p in net]
        driven = [v for v in driven if v is not None]
        if stuck or driven:
            values = stuck + driven
            if len(set(values)) > 1:
                self.contention.append((side, pin))
                return stuck[0] if stuck else 0
            return values[0]
        up = down = 0
        for s, p in net:
            pull = self._ports[s].state(p).pull
            up += pull == Pull.UP
            down += pull == Pull.DOWN
            if p in EXTERNAL_PULLUP:
                up += 2  # 1,8k is veel sterker dan de interne ~50k
        return 1 if up > down else 0
