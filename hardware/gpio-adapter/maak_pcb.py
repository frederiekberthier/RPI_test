"""Ontwerpt de GPIO-adapter: een PCB met één koperlaag tussen TEST-SERVER en TEST-CLIENT.

    python hardware/gpio-adapter/maak_pcb.py            # schrijft alles naast dit script
    python hardware/gpio-adapter/maak_pcb.py --check    # controleert alleen of de uitvoer nog klopt met het script

Wat de print doet (zie docs/pcb.md): twee 2x20-boxheaders, elk met een lintkabel naar een Pi. Pin n van de ene header is
met pin n van de andere verbonden: 26 GPIO-lijnen via een weerstand van 220 ohm, de 8 GND-pinnen rechtstreeks. 3V3, 5V
en de ID-pinnen zijn nergens mee verbonden, dus er is geen route waarlangs twee voedingen elkaar kunnen raken.

Pinnummering (belangrijk): beide headers staan met de lange kant horizontaal en pin 1 links. Zoals op de GPIO-header van
een Pi ligt pin 2 dan boven pin 1: de bovenste rij heeft de even pinnen (2, 4, 6, ...) en de onderste de oneven. Een
gespiegelde nummering bestaat niet bij een echte connector, en zou 5V op een GPIO-lijn zetten.

Waarom dit met één laag lukt zonder draadbruggen: de tweede header staat 1,27 mm naar links verschoven. Daardoor loopt
elke verbinding als een rechte, verticale baan van de ene header naar de andere (de buitenste pinrij komt via een
45-graden-hoekje door de ruimte tussen twee binnenste pinnen). Er kruist dus niets. De weerstanden staan in die banen;
omdat banen maar 1,27 mm uit elkaar liggen en een weerstand 2,5 mm breed is, staan ze verdeeld over drie niveaus
(plaats van de baan modulo 3).

De pinindeling komt uit rpitest.gpio.ports, zodat tekening, print en software niet uit elkaar kunnen lopen.
Alle bestanden worden hieruit gegenereerd; pas dit script aan, niet de uitvoer.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from rpitest.gpio.ports import (
    GND_HEADER_PINS,
    HEADER_PIN,
    POWER_HEADER_PINS,
)

NAME = "gpio-adapter"
REVISION = "1"

# ---------------------------------------------------------------- maten (mm)
PITCH, HALF = 2.54, 1.27
PAD, DRILL, TRACE = 1.7, 1.0, 0.3  # koperpad, boorgat en baanbreedte
MASK_EXPAND = 0.05  # soldeermasker-opening per kant rond een pad
MIN_CLEARANCE = 0.2  # kleinste afstand tussen koper van verschillende netten
MIN_EDGE = 0.5  # kleinste afstand van koper tot de rand
R_PITCH, R_BODY_L, R_BODY_D = 7.62, 6.3, 2.5  # 220 ohm, 0,25 W, axiaal (DIN0207)
HEADER_L, HEADER_W = 53.34, 8.9  # boxheader 2x20, afmetingen van het plastic
BOARD_W = 70.0
MARGIN = 7.0  # van de printrand tot de headerbehuizing
HOLE_D, HOLE_INSET = 3.2, 4.0  # M3-montagegaten
LEVELS = 3  # niveaus voor de weerstanden
LEVEL_STEP = R_PITCH + 1.7  # paden van twee niveaus komen zo ver van elkaar
SILK = 0.2  # lijndikte van de zeefdruk
TEXT_H = 1.8

PIN_BY_HEADER = {pin: gpio for gpio, pin in HEADER_PIN.items()}
TEST_SERVER, TEST_CLIENT = "TEST-SERVER", "TEST-CLIENT"


def pin_kind(pin: int) -> str:
    """gpio, gnd, power of id voor fysieke pin 1 tot en met 40."""
    if pin in GND_HEADER_PINS:
        return "gnd"
    if pin in POWER_HEADER_PINS:
        return "power"
    if pin in (27, 28):
        return "id"
    return "gpio"


# ---------------------------------------------------------------- stroomlettertype voor de zeefdruk
# Elk teken staat op een raster van 4 breed en 6 hoog (y omhoog) als lijst van polylijnen.
GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "A": [[(0, 0), (0, 4), (2, 6), (4, 4), (4, 0)], [(0, 3), (4, 3)]],
    "B": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)], [(3, 3), (4, 2), (4, 1), (3, 0), (0, 0)]],
    "C": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1)]],
    "D": [[(0, 0), (0, 6), (2, 6), (4, 4), (4, 2), (2, 0), (0, 0)]],
    "E": [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    "G": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0), (3, 0), (4, 1), (4, 3), (2, 3)]],
    "I": [[(1, 6), (3, 6)], [(2, 6), (2, 0)], [(1, 0), (3, 0)]],
    "L": [[(0, 6), (0, 0), (4, 0)]],
    "N": [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    "O": [[(1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0)]],
    "P": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)]],
    "R": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)], [(2, 3), (4, 0)]],
    "S": [[(4, 5), (3, 6), (1, 6), (0, 5), (0, 4), (1, 3), (3, 3), (4, 2), (4, 1), (3, 0), (1, 0), (0, 1)]],
    "T": [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    "U": [[(0, 6), (0, 1), (1, 0), (3, 0), (4, 1), (4, 6)]],
    "V": [[(0, 6), (2, 0), (4, 6)]],
    "0": [[(1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 1), (3, 0), (1, 0)], [(0.6, 0.6), (3.4, 5.4)]],
    "1": [[(1, 5), (2, 6), (2, 0)], [(1, 0), (3, 0)]],
    "2": [[(0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (0, 0), (4, 0)]],
    "-": [[(0.5, 3), (3.5, 3)]],
    " ": [],
}
GLYPH_W, GLYPH_H, GLYPH_GAP = 4.0, 6.0, 1.6


def text_width(text: str, height: float) -> float:
    scale = height / GLYPH_H
    return (len(text) * (GLYPH_W + GLYPH_GAP) - GLYPH_GAP) * scale


def text_strokes(text: str, x: float, y_top: float, height: float) -> list[tuple[float, float, float, float]]:
    """Lijnstukken (x1, y1, x2, y2) in ontwerpcoördinaten (y omlaag) voor `text`, linksboven in (x, y_top)."""
    scale = height / GLYPH_H
    strokes = []
    for index, char in enumerate(text):
        if char not in GLYPHS:
            raise ValueError(f"teken {char!r} zit niet in het zeefdruklettertype")
        ox = x + index * (GLYPH_W + GLYPH_GAP) * scale
        for poly in GLYPHS[char]:
            points = [(ox + px * scale, y_top + (GLYPH_H - py) * scale) for px, py in poly]
            strokes += [(*a, *b) for a, b in zip(points, points[1:], strict=False)]
            if len(points) == 1:
                strokes.append((*points[0], *points[0]))
    return strokes


# ---------------------------------------------------------------- het ontwerp
@dataclass
class Pad:
    ref: str
    number: str
    x: float
    y: float
    net: str | None
    square: bool = False


@dataclass
class Track:
    x1: float
    y1: float
    x2: float
    y2: float
    net: str
    width: float = TRACE


@dataclass
class Design:
    width: float
    height: float
    pads: list[Pad] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    holes: list[tuple[float, float]] = field(default_factory=list)  # montagegaten
    silk_lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    texts: list[tuple[str, float, float, float]] = field(default_factory=list)  # tekst, x, y_top, hoogte
    headers: dict[str, tuple[float, float]] = field(default_factory=dict)  # ref -> (x van pin 1, y van pin 1)
    resistors: dict[str, tuple[float, float]] = field(default_factory=dict)  # ref -> (x, y van pad 1)

    def silk_strokes(self) -> list[tuple[float, float, float, float]]:
        strokes = list(self.silk_lines)
        for text, x, y, h in self.texts:
            strokes += text_strokes(text, x, y, h)
        return strokes


def rect_lines(cx: float, cy: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    x1, x2, y1, y2 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
    return [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]


def build() -> Design:
    """Alle coördinaten in mm met de oorsprong linksboven op de print en y naar beneden (zoals KiCad)."""
    # de twee headers: A (TEST-SERVER) boven, B (TEST-CLIENT) onder en 1,27 mm naar links verschoven
    span = 19 * PITCH  # afstand tussen pin 1 en pin 39 van een header
    xa0 = BOARD_W / 2 + HALF / 2 - span / 2  # x van kolom 1 op header A; het paar staat gecentreerd op de print
    xb0 = xa0 - HALF
    ya_top = MARGIN + HEADER_W / 2 - HALF  # buitenste rij van A (even pinnen)
    ya_bot = ya_top + PITCH  # binnenste rij van A (oneven pinnen)
    body_bottom_a = ya_top + HALF + HEADER_W / 2
    y_first = body_bottom_a + 0.85 + 0.5  # eerste weerstandspad
    y_last = y_first + (LEVELS - 1) * LEVEL_STEP + R_PITCH
    body_top_b = y_last + 0.85 + 0.5
    yb_top = body_top_b + HEADER_W / 2 - HALF  # binnenste rij van B (even pinnen)
    yb_bot = yb_top + PITCH  # buitenste rij van B (oneven pinnen)
    height = yb_top + HALF + HEADER_W / 2 + MARGIN

    d = Design(BOARD_W, height)
    d.headers = {"J1": (xa0, ya_bot), "J2": (xb0, yb_bot)}  # plaats van pin 1

    def column(pin: int) -> int:
        return (pin + 1) // 2 - 1

    def line_x(pin: int) -> float:
        """x van de verticale baan van `pin`: even pinnen (buitenrij op A) lopen links van hun kolom door het gat tussen twee pinnen."""
        return xa0 + PITCH * column(pin) - (0.0 if pin % 2 else HALF)

    for ref, x0, y_even, y_odd in (("J1", xa0, ya_top, ya_bot), ("J2", xb0, yb_top, yb_bot)):
        for pin in range(1, 41):
            x = x0 + PITCH * column(pin)
            y = y_odd if pin % 2 else y_even
            kind = pin_kind(pin)
            net = None
            if kind == "gnd":
                net = "GND"
            elif kind == "gpio":
                side = "A" if ref == "J1" else "B"
                net = f"GPIO{PIN_BY_HEADER[pin]}_{side}"
            d.pads.append(Pad(ref, str(pin), x, y, net, square=(pin == 1)))

    def add(net: str, points: list[tuple[float, float]]) -> None:
        for (x1, y1), (x2, y2) in zip(points, points[1:], strict=False):
            d.tracks.append(Track(x1, y1, x2, y2, net))

    def path_a(pin: int, until: float) -> list[tuple[float, float]]:
        """Van de pad op header A recht omlaag tot `until`."""
        x = xa0 + PITCH * column(pin)
        if pin % 2 == 0:  # buitenste rij: eerst schuin door het gat tussen twee binnenste pinnen
            return [(x, ya_top), (line_x(pin), ya_top + HALF), (line_x(pin), until)]
        return [(x, ya_bot), (line_x(pin), until)]

    def path_b(pin: int, start: float) -> list[tuple[float, float]]:
        """Van `start` recht omlaag naar de pad op header B."""
        x = xb0 + PITCH * column(pin)
        if pin % 2 == 0:
            return [(line_x(pin), start), (x, yb_top)]
        return [(line_x(pin), start), (line_x(pin), yb_bot - HALF), (x, yb_bot)]

    for pin in range(1, 41):
        kind = pin_kind(pin)
        if kind == "gnd":
            middle = (y_first + y_last) / 2
            add("GND", path_a(pin, middle) + path_b(pin, middle)[1:])
        elif kind == "gpio":
            gpio = PIN_BY_HEADER[pin]
            level = round((line_x(pin) - xa0) / HALF) % LEVELS  # buurbanen (1,27 mm) komen op verschillende niveaus
            y1 = y_first + level * LEVEL_STEP
            y2 = y1 + R_PITCH
            ref = f"R{gpio}"
            d.resistors[ref] = (line_x(pin), y1)
            d.pads.append(Pad(ref, "1", line_x(pin), y1, f"GPIO{gpio}_A"))
            d.pads.append(Pad(ref, "2", line_x(pin), y2, f"GPIO{gpio}_B"))
            add(f"GPIO{gpio}_A", path_a(pin, y1))
            add(f"GPIO{gpio}_B", path_b(pin, y2))
            # zeefdruk: de zijkanten van het weerstandslichaam, kort voor de pads
            top, bottom = y1 + 0.85 + 0.2, y2 - 0.85 - 0.2
            x = line_x(pin)
            d.silk_lines += [(x - R_BODY_D / 2, top, x - R_BODY_D / 2, bottom), (x + R_BODY_D / 2, top, x + R_BODY_D / 2, bottom)]

    for x0, y_pin1 in ((xa0, ya_bot), (xb0, yb_bot)):
        d.silk_lines += rect_lines(x0 + span / 2, y_pin1 - HALF, HEADER_L, HEADER_W)  # behuizing van de boxheader
        d.texts.append(("1", x0 - PITCH - 0.8 - text_width("1", TEXT_H), y_pin1 - TEXT_H / 2, TEXT_H))  # naast pin 1

    for x, y in ((HOLE_INSET, HOLE_INSET), (BOARD_W - HOLE_INSET, HOLE_INSET),
                 (HOLE_INSET, height - HOLE_INSET), (BOARD_W - HOLE_INSET, height - HOLE_INSET)):
        d.holes.append((x, y))

    d.texts += [
        (f"A {TEST_SERVER}", 8.0, 2.2, TEXT_H),
        ("GPIO-ADAPTER", BOARD_W - 8.0 - text_width("GPIO-ADAPTER", TEXT_H), 2.2, TEXT_H),
        (f"B {TEST_CLIENT}", 8.0, height - 2.2 - TEXT_H, TEXT_H),
        ("220R", BOARD_W - 8.0 - text_width("220R", TEXT_H), height - 2.2 - TEXT_H, TEXT_H),
    ]
    return d


# ---------------------------------------------------------------- Gerber (RS-274X) en boorbestand
def _fmt(value: float) -> str:
    return str(round(value * 1_000_000))


class Gerber:
    """Minimale RS-274X-schrijver: cirkel- en rechthoekaperturen, lijnen en flashes. Eenheden mm, formaat 4.6."""

    def __init__(self, function: str, height: float, polarity: str = "Positive"):
        self.function, self.height, self.polarity = function, height, polarity
        self.apertures: dict[tuple, int] = {}
        self.body: list[str] = []
        self.current: int | None = None

    def _select(self, shape: str, *size: float) -> None:
        key = (shape, *size)
        if key not in self.apertures:
            self.apertures[key] = 10 + len(self.apertures)
        code = self.apertures[key]
        if code != self.current:
            self.body.append(f"D{code}*")
            self.current = code

    def _xy(self, x: float, y: float) -> str:
        return f"X{_fmt(x)}Y{_fmt(self.height - y)}"  # Gerber heeft y omhoog

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float) -> None:
        self._select("C", width)
        self.body.append(f"{self._xy(x1, y1)}D02*")
        self.body.append(f"{self._xy(x2, y2)}D01*")

    def flash_circle(self, x: float, y: float, diameter: float) -> None:
        self._select("C", diameter)
        self.body.append(f"{self._xy(x, y)}D03*")

    def flash_rect(self, x: float, y: float, w: float, h: float) -> None:
        self._select("R", w, h)
        self.body.append(f"{self._xy(x, y)}D03*")

    def render(self) -> str:
        head = [
            "G04 Gegenereerd door hardware/gpio-adapter/maak_pcb.py*",
            f"%TF.GenerationSoftware,rpitest,maak_pcb,{REVISION}*%",
            f"%TF.FileFunction,{self.function}*%",
            f"%TF.FilePolarity,{self.polarity}*%",
            "%FSLAX46Y46*%",
            "%MOMM*%",
        ]
        for (shape, *size), code in self.apertures.items():
            head.append(f"%ADD{code}{shape},{'X'.join(f'{s:.6f}' for s in size)}*%")
        return "\n".join([*head, "G01*", *self.body, "M02*", ""])


def copper_gerber(d: Design) -> str:
    g = Gerber("Copper,L1,Bot", d.height)
    for t in d.tracks:
        g.line(t.x1, t.y1, t.x2, t.y2, t.width)
    for p in d.pads:
        g.flash_rect(p.x, p.y, PAD, PAD) if p.square else g.flash_circle(p.x, p.y, PAD)
    return g.render()


def mask_gerber(d: Design) -> str:
    g = Gerber("Soldermask,Bot", d.height, "Negative")
    size = PAD + 2 * MASK_EXPAND
    for p in d.pads:
        g.flash_rect(p.x, p.y, size, size) if p.square else g.flash_circle(p.x, p.y, size)
    return g.render()


def silk_gerber(d: Design) -> str:
    g = Gerber("Legend,Top", d.height)
    for x1, y1, x2, y2 in d.silk_strokes():
        g.line(x1, y1, x2, y2, SILK)
    return g.render()


def outline_gerber(d: Design) -> str:
    g = Gerber("Profile,NP", d.height)
    for x1, y1, x2, y2 in rect_lines(d.width / 2, d.height / 2, d.width, d.height):
        g.line(x1, y1, x2, y2, 0.1)
    return g.render()


def holes_of(d: Design) -> list[tuple[float, float, float]]:
    """(x, y, diameter) van alle gaten: pads en montagegaten."""
    return [(p.x, p.y, DRILL) for p in d.pads] + [(x, y, HOLE_D) for x, y in d.holes]


def drill_file(d: Design) -> str:
    diameters = sorted({dia for _, _, dia in holes_of(d)})
    lines = ["M48", "; Gegenereerd door hardware/gpio-adapter/maak_pcb.py", "; FORMAT={-:-/ absolute / metric / decimal}",
             "FMAT,2", "METRIC,TZ", "; #@! TF.FileFunction,NonPlated,1,1,NPTH"]  # één koperlaag: geen doormetallisering
    lines += [f"T{i}C{dia:.3f}" for i, dia in enumerate(diameters, 1)]
    lines += ["%", "G90", "G05"]
    for i, dia in enumerate(diameters, 1):
        lines.append(f"T{i}")
        lines += [f"X{x:.3f}Y{d.height - y:.3f}" for x, y, size in holes_of(d) if size == dia]
    lines += ["T0", "M30", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- SVG-voorbeeld (bovenkant, koper doorschijnend)
def to_svg(d: Design) -> str:
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 {d.width + 4:.2f} {d.height + 4:.2f}" '
           f'width="{(d.width + 4) * 10:.0f}" height="{(d.height + 4) * 10:.0f}" font-family="sans-serif">',
           '<title>GPIO-adapter, bovenkant (koper zit aan de onderkant en schijnt door)</title>',
           f'<rect x="0" y="0" width="{d.width}" height="{d.height}" rx="0.5" fill="#1d6b3a" stroke="#0d3b1f" stroke-width="0.2"/>']
    for t in d.tracks:
        out.append(f'<line x1="{t.x1:.3f}" y1="{t.y1:.3f}" x2="{t.x2:.3f}" y2="{t.y2:.3f}" stroke="#d99a3a" '
                   f'stroke-width="{t.width}" stroke-linecap="round" opacity="0.85"/>')
    for p in d.pads:
        if p.square:
            out.append(f'<rect x="{p.x - PAD / 2:.3f}" y="{p.y - PAD / 2:.3f}" width="{PAD}" height="{PAD}" fill="#e6b455"/>')
        else:
            out.append(f'<circle cx="{p.x:.3f}" cy="{p.y:.3f}" r="{PAD / 2}" fill="#e6b455"/>')
        out.append(f'<circle cx="{p.x:.3f}" cy="{p.y:.3f}" r="{DRILL / 2}" fill="#101010"/>')
    for x, y in d.holes:
        out.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{HOLE_D / 2}" fill="#101010"/>')
    for x1, y1, x2, y2 in d.silk_strokes():
        out.append(f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" stroke="#f4f4f0" '
                   f'stroke-width="{SILK}" stroke-linecap="round"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- BOM en KiCad
def bom_csv(d: Design) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Aantal", "Referenties", "Waarde", "Onderdeel", "Opmerking"])
    resistors = sorted(d.resistors, key=lambda r: int(r[1:]))
    writer.writerow([len(resistors), " ".join(resistors), "220 ohm",
                     "weerstand axiaal 0,25 W, 5 % of beter, DIN0207, steek 7,62 mm", "één per GPIO-lijn"])
    writer.writerow([2, "J1 J2", "2x20", "boxheader (shrouded IDC) 2x20, 2,54 mm, recht, soldeer",
                     "J1 = TEST-SERVER, J2 = TEST-CLIENT"])
    writer.writerow([2, "", "40-polig", "lintkabel met twee IDC-connectoren (zoals voor de GPIO van een Pi), 1:1",
                     "één per Pi; niet kruisen of draaien"])
    writer.writerow([4, "H1 H2 H3 H4", "M3", "afstandsbusje of schroef", "optioneel, voor montage"])
    return buf.getvalue()


def kicad_pcb(d: Design) -> str:
    nets = sorted({p.net for p in d.pads if p.net})
    index = {name: i for i, name in enumerate(nets, 1)}

    def net(name: str | None) -> str:
        return f'(net {index[name]} "{name}")' if name else ""

    def num(value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".") or "0"

    o = ['(kicad_pcb (version 20221018) (generator "maak_pcb")', "  (general (thickness 1.6))", '  (paper "A4")',
         "  (layers"]
    for number, name, kind, alias in (
            (0, "F.Cu", "signal", ""), (31, "B.Cu", "signal", ""), (32, "B.Adhes", "user", "B.Adhesive"),
            (33, "F.Adhes", "user", "F.Adhesive"), (34, "B.Paste", "user", ""), (35, "F.Paste", "user", ""),
            (36, "B.SilkS", "user", "B.Silkscreen"), (37, "F.SilkS", "user", "F.Silkscreen"), (38, "B.Mask", "user", ""),
            (39, "F.Mask", "user", ""), (40, "Dwgs.User", "user", "User.Drawings"), (41, "Cmts.User", "user", "User.Comments"),
            (42, "Eco1.User", "user", "User.Eco1"), (43, "Eco2.User", "user", "User.Eco2"), (44, "Edge.Cuts", "user", ""),
            (45, "Margin", "user", ""), (46, "B.CrtYd", "user", "B.Courtyard"), (47, "F.CrtYd", "user", "F.Courtyard"),
            (48, "B.Fab", "user", ""), (49, "F.Fab", "user", "")):
        o.append(f'    ({number} "{name}" {kind}' + (f' "{alias}"' if alias else "") + ")")
    o += ["  )", "  (setup (pad_to_mask_clearance 0))", '  (net 0 "")']
    o += [f'  (net {i} "{name}")' for name, i in index.items()]

    def pad_line(p: Pad, ox: float, oy: float) -> str:
        shape = "rect" if p.square else "circle"
        return (f'    (pad "{p.number}" thru_hole {shape} (at {num(p.x - ox)} {num(p.y - oy)}) (size {num(PAD)} {num(PAD)}) '
                f'(drill {num(DRILL)}) (layers "B.Cu" "B.Mask") {net(p.net)})')

    def footprint(name: str, ref: str, value: str, x: float, y: float, pads: list[str]) -> list[str]:
        return ([f'  (footprint "{name}" (layer "F.Cu") (at {num(x)} {num(y)})',
                 f'    (property "Reference" "{ref}" (at 0 -2) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))',
                 f'    (property "Value" "{value}" (at 0 2) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))']
                + pads + ["  )"])

    for ref, (x0, y0) in d.headers.items():
        pads = [pad_line(p, x0, y0) for p in d.pads if p.ref == ref]
        o += footprint("IDC-Header_2x20_P2.54mm_Horizontal_Mirrored", ref, "2x20", x0, y0, pads)
    for ref, (x0, y0) in sorted(d.resistors.items(), key=lambda kv: int(kv[0][1:])):
        pads = [pad_line(p, x0, y0) for p in d.pads if p.ref == ref]
        o += footprint("R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm", ref, "220", x0, y0, pads)
    for i, (x, y) in enumerate(d.holes, 1):
        o += footprint("MountingHole_3.2mm_M3", f"H{i}", "M3", x, y,
                       [f'    (pad "" np_thru_hole circle (at 0 0) (size {num(HOLE_D)} {num(HOLE_D)}) (drill {num(HOLE_D)}) '
                        f'(layers "*.Cu" "*.Mask"))'])
    for t in d.tracks:
        o.append(f'  (segment (start {num(t.x1)} {num(t.y1)}) (end {num(t.x2)} {num(t.y2)}) (width {num(t.width)}) '
                 f'(layer "B.Cu") (net {index[t.net]}))')
    for x1, y1, x2, y2 in rect_lines(d.width / 2, d.height / 2, d.width, d.height):
        o.append(f'  (gr_line (start {num(x1)} {num(y1)}) (end {num(x2)} {num(y2)}) (layer "Edge.Cuts") (width 0.1))')
    for x1, y1, x2, y2 in d.silk_lines:
        o.append(f'  (gr_line (start {num(x1)} {num(y1)}) (end {num(x2)} {num(y2)}) (layer "F.SilkS") (width {num(SILK)}))')
    for text, x, y, h in d.texts:
        o.append(f'  (gr_text "{text}" (at {num(x)} {num(y + h / 2)}) (layer "F.SilkS") '
                 f'(effects (font (size {num(h)} {num(h)}) (thickness {num(SILK)})) (justify left)))')
    o.append(")")
    return "\n".join(o) + "\n"


# ---------------------------------------------------------------- uitvoer
def zip_bytes(files: dict[str, str]) -> bytes:
    """Een zip met vaste tijdstempels, zodat dezelfde invoer altijd dezelfde bytes geeft."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, content.replace("\r\n", "\n").encode("utf-8"))
    return buf.getvalue()


def outputs(d: Design | None = None) -> dict[str, bytes]:
    """Pad (relatief aan deze map) -> inhoud van elk gegenereerd bestand."""
    d = d or build()
    gerbers = {
        f"{NAME}-B_Cu.gbl": copper_gerber(d),
        f"{NAME}-B_Mask.gbs": mask_gerber(d),
        f"{NAME}-F_Silkscreen.gto": silk_gerber(d),
        f"{NAME}-Edge_Cuts.gm1": outline_gerber(d),
        f"{NAME}.drl": drill_file(d),
    }
    files = {f"gerber/{name}": text.encode() for name, text in gerbers.items()}
    files[f"{NAME}-gerber.zip"] = zip_bytes(gerbers)
    files[f"kicad/{NAME}.kicad_pcb"] = kicad_pcb(d).encode()
    files["bom.csv"] = bom_csv(d).encode()
    files["voorbeeld-bovenkant.svg"] = to_svg(d).encode()
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="schrijf niets; faal als de bestanden niet meer kloppen")
    args = parser.parse_args(argv)
    files = outputs()
    stale = [name for name, data in files.items() if not (HERE / name).exists() or (HERE / name).read_bytes() != data]
    if args.check:
        for name in stale:
            print(f"verouderd: {name}")
        return 1 if stale else 0
    for name, data in files.items():
        target = HERE / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    d = build()
    print(f"{len(files)} bestanden geschreven in {HERE}; print {d.width:.1f} x {d.height:.1f} mm, "
          f"{len(d.resistors)} weerstanden, {len(d.holes)} montagegaten")
    return 0


if __name__ == "__main__":
    sys.exit(main())
