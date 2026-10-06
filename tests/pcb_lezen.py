"""Leest de gegenereerde Gerber- en boorbestanden terug en rekent erop (verbindingen, afstanden).

Bewust los van hardware/gpio-adapter/maak_pcb.py: de tests controleren wat de fabrikant straks krijgt, niet wat het
script denkt te hebben geschreven."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Shape:
    """Een capsule: lijnstuk met straal r (een cirkel is een lijnstuk van lengte 0)."""

    x1: float
    y1: float
    x2: float
    y2: float
    r: float
    kind: str = "track"  # track of pad
    square: bool = False


def parse_gerber(text: str) -> tuple[list[tuple[float, float, float, float, float]], list[tuple[float, float, str, tuple]]]:
    """(lijnen, flashes) in Gerber-coördinaten (mm, y omhoog). Lijn = (x1, y1, x2, y2, breedte)."""
    assert "%MOMM*%" in text and "%FSLAX46Y46*%" in text, "verwacht millimeters en formaat 4.6"
    assert text.rstrip().endswith("M02*"), "bestand eindigt niet met M02"
    apertures: dict[int, tuple[str, tuple]] = {}
    for code, shape, sizes in re.findall(r"%ADD(\d+)([CR]),([0-9.X]+)\*%", text):
        apertures[int(code)] = (shape, tuple(float(v) for v in sizes.split("X")))
    lines, flashes = [], []
    current, position = None, (0.0, 0.0)
    for raw in text.splitlines():
        raw = raw.strip()
        if match := re.fullmatch(r"D(\d+)\*", raw):
            current = apertures[int(match.group(1))]
            continue
        if match := re.fullmatch(r"X(-?\d+)Y(-?\d+)D0([123])\*", raw):
            x, y, op = int(match.group(1)) / 1e6, int(match.group(2)) / 1e6, match.group(3)
            if op == "2":
                position = (x, y)
            elif op == "1":
                lines.append((*position, x, y, current[1][0]))
                position = (x, y)
            else:
                flashes.append((x, y, current[0], current[1]))
                position = (x, y)
    return lines, flashes


def parse_drill(text: str) -> list[tuple[float, float, float]]:
    """(x, y, diameter) in Gerber-coördinaten."""
    assert "METRIC" in text and text.rstrip().endswith("M30")
    tools = {int(n): float(d) for n, d in re.findall(r"^T(\d+)C([0-9.]+)$", text, re.MULTILINE)}
    holes, tool = [], None
    for raw in text.splitlines():
        if match := re.fullmatch(r"T(\d+)", raw.strip()):
            tool = int(match.group(1)) or None
        elif match := re.fullmatch(r"X(-?[0-9.]+)Y(-?[0-9.]+)", raw.strip()):
            holes.append((float(match.group(1)), float(match.group(2)), tools[tool]))
    return holes


def shapes_of(lines, flashes, height: float) -> list[Shape]:
    """Koper als capsules in ontwerpcoördinaten (y omlaag). Een vierkante pad telt als zijn omgeschreven cirkel."""
    shapes = []
    for x1, y1, x2, y2, width in lines:
        shapes.append(Shape(x1, height - y1, x2, height - y2, width / 2))
    for x, y, kind, size in flashes:
        radius = size[0] / 2 if kind == "C" else math.hypot(size[0], size[1]) / 2
        shapes.append(Shape(x, height - y, x, height - y, radius, "pad", square=kind == "R"))
    return shapes


def _point_segment(px, py, x1, y1, x2, y2) -> float:
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _segments_cross(a: Shape, b: Shape) -> bool:
    def side(ax, ay, bx, by, cx, cy):
        return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)

    d1 = side(a.x1, a.y1, a.x2, a.y2, b.x1, b.y1)
    d2 = side(a.x1, a.y1, a.x2, a.y2, b.x2, b.y2)
    d3 = side(b.x1, b.y1, b.x2, b.y2, a.x1, a.y1)
    d4 = side(b.x1, b.y1, b.x2, b.y2, a.x2, a.y2)
    return d1 * d2 < 0 and d3 * d4 < 0


def gap(a: Shape, b: Shape) -> float:
    """Kleinste afstand tussen de randen van twee capsules (negatief als ze elkaar overlappen)."""
    if _segments_cross(a, b):
        return -min(a.r, b.r)
    centres = min(_point_segment(a.x1, a.y1, b.x1, b.y1, b.x2, b.y2), _point_segment(a.x2, a.y2, b.x1, b.y1, b.x2, b.y2),
                  _point_segment(b.x1, b.y1, a.x1, a.y1, a.x2, a.y2), _point_segment(b.x2, b.y2, a.x1, a.y1, a.x2, a.y2))
    return centres - a.r - b.r


def islands(shapes: list[Shape]) -> list[list[int]]:
    """Groepen indices van koper dat elkaar raakt (samenhangend koper = één net)."""
    parent = list(range(len(shapes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if gap(shapes[i], shapes[j]) <= 0:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(shapes)):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())
