"""Minimale nabootsing van de gpiod 2.x-API, gebaseerd op de echte signaturen
(request_lines, LineSettings, LineRequest.reconfigure_lines/get_values/release, Chip.get_info).
Dient om de logica van rpitest.gpio.real op Windows te testen; het bewijst niets over echte pinnen."""

from __future__ import annotations

import enum
import types
from dataclasses import dataclass


class Direction(enum.Enum):
    AS_IS = 0
    INPUT = 1
    OUTPUT = 2


class Bias(enum.Enum):
    AS_IS = 0
    DISABLED = 1
    PULL_UP = 2
    PULL_DOWN = 3


class Value(enum.Enum):
    INACTIVE = 0
    ACTIVE = 1


line = types.SimpleNamespace(Direction=Direction, Bias=Bias, Value=Value)


@dataclass
class LineSettings:
    direction: Direction = Direction.AS_IS
    bias: Bias = Bias.AS_IS
    output_value: Value = Value.INACTIVE


class LineRequest:
    def __init__(self, config):
        self.config = dict(config)
        self.reconfigure_calls = 0
        self.released = False

    def reconfigure_lines(self, config):
        self.reconfigure_calls += 1
        self.config = dict(config)

    def get_values(self, lines=None):
        out = []
        for p in lines:
            s = self.config[p]
            if s.direction is Direction.OUTPUT:
                out.append(s.output_value)
            else:
                out.append(Value.ACTIVE if s.bias is Bias.PULL_UP else Value.INACTIVE)
        return out

    def release(self):
        self.released = True


@dataclass
class ChipInfo:
    name: str
    label: str
    num_lines: int


class FakeSystem:
    """Wat er 'in /dev' staat: pad -> (label, aantal lijnen). Bezette lijnen: set van offsets."""

    def __init__(self, chips, busy=()):
        self.chips = chips
        self.busy = set(busy)
        self.requests: list[LineRequest] = []

    def module(self):
        system = self
        mod = types.ModuleType("gpiod")
        mod.line = line
        mod.LineSettings = LineSettings

        class Chip:
            def __init__(self, path):
                if path not in system.chips:
                    raise FileNotFoundError(path)
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            def get_info(self):
                label, n = system.chips[self.path]
                return ChipInfo(self.path.rsplit("/", 1)[-1], label, n)

        def request_lines(path, consumer=None, config=None):
            if system.busy & set(config):
                raise OSError(16, "Device or resource busy")
            req = LineRequest(config)
            system.requests.append(req)
            return req

        mod.Chip = Chip
        mod.request_lines = request_lines
        return mod
