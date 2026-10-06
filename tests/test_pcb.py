"""De GPIO-adapter (hardware/gpio-adapter): klopt de print met de bedrading uit de handleiding en met de software?

De tests lezen de Gerber- en boorbestanden terug die naar de fabrikant gaan en rekenen daar zelf op: welke pads
hangen aan elkaar, hoe dicht liggen verschillende netten bij elkaar, past alles op de print."""

import importlib.util
import math
import re
import sys
import zipfile
from pathlib import Path

import pytest
from pcb_lezen import Shape, gap, islands, parse_drill, parse_gerber, shapes_of

from rpitest.gpio.ports import GND_HEADER_PINS, HEADER_PIN, PINS, POWER_HEADER_PINS

ROOT = Path(__file__).resolve().parents[1]
PCB = ROOT / "hardware" / "gpio-adapter"
NAME = "gpio-adapter"

PITCH = 2.54
MIN_CLEARANCE = 0.2  # tussen koper van verschillende netten
MIN_TRACK = 0.25
MIN_RING = 0.3  # kopering rond een gat
MIN_EDGE = 0.5  # koper tot printrand
R_PITCH = 7.62


def load_module():
    spec = importlib.util.spec_from_file_location("maak_pcb", PCB / "maak_pcb.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses zoekt de module hier op
    spec.loader.exec_module(module)
    return module


maak_pcb = load_module()


def read(name: str) -> str:
    return (PCB / "gerber" / name).read_text(encoding="utf-8")


class Board:
    """Alles wat uit de bestanden terug te lezen is, in ontwerpcoördinaten (y omlaag)."""

    def __init__(self):
        outline_lines, _ = parse_gerber(read(f"{NAME}-Edge_Cuts.gm1"))
        xs = [v for x1, y1, x2, y2, _w in outline_lines for v in (x1, x2)]
        ys = [v for x1, y1, x2, y2, _w in outline_lines for v in (y1, y2)]
        assert min(xs) == 0 and min(ys) == 0
        self.width, self.height = max(xs), max(ys)

        copper_lines, copper_flashes = parse_gerber(read(f"{NAME}-B_Cu.gbl"))
        self.copper = shapes_of(copper_lines, copper_flashes, self.height)
        self.pads = [s for s in self.copper if s.kind == "pad"]
        self.tracks = [s for s in self.copper if s.kind == "track"]
        self.track_widths = {round(w, 6) for *_xy, w in copper_lines}

        self.holes = [(x, self.height - y, d) for x, y, d in parse_drill((PCB / "gerber" / f"{NAME}.drl").read_text())]
        self.lead_holes = [(x, y) for x, y, d in self.holes if d == 1.0]
        self.mount_holes = [(x, y) for x, y, d in self.holes if d == 3.2]

        silk_lines, _ = parse_gerber(read(f"{NAME}-F_Silkscreen.gto"))
        self.silk = [Shape(x1, self.height - y1, x2, self.height - y2, w / 2) for x1, y1, x2, y2, w in silk_lines]
        _, mask_flashes = parse_gerber(read(f"{NAME}-B_Mask.gbs"))
        self.mask = [(x, self.height - y, kind, size) for x, y, kind, size in mask_flashes]

        self._find_headers()
        self.groups = islands(self.copper)
        self.group_of = {i: g for g, members in enumerate(self.groups) for i in members}

    def _find_headers(self) -> None:
        """Leid uit de gaten af welke pad welke pin van welke header is: twee headers van 2 rijen van 20."""
        rows: dict[float, list[float]] = {}
        for x, y in self.lead_holes:
            rows.setdefault(round(y, 3), []).append(x)
        full = sorted(y for y, xs in rows.items() if len(xs) == 20)
        assert len(full) == 4, f"verwacht vier rijen van 20 gaten, kreeg {sorted((y, len(xs)) for y, xs in rows.items())}"
        self.header_pin: dict[tuple[float, float], tuple[str, int]] = {}
        for header, (top, bottom) in (("A", full[:2]), ("B", full[2:])):
            assert math.isclose(bottom - top, PITCH, abs_tol=1e-3)
            columns = sorted(rows[top])
            assert all(math.isclose(b - a, PITCH, abs_tol=1e-3) for a, b in zip(columns, columns[1:], strict=False))
            assert sorted(rows[bottom]) == columns
            for k, x in enumerate(columns, 1):
                # Zoals op de GPIO-header van een Pi: pin 1 links, en pin 2 ligt BOVEN pin 1. Een gespiegelde nummering
                # bestaat niet bij een echte connector; dan zou een GPIO-lijn op 5V of 3V3 uitkomen.
                self.header_pin[(round(x, 3), top)] = (header, 2 * k)  # bovenste rij: even pinnen
                self.header_pin[(round(x, 3), bottom)] = (header, 2 * k - 1)  # onderste rij: oneven pinnen

    def pad_index(self, x: float, y: float) -> int:
        matches = [i for i, s in enumerate(self.copper) if s.kind == "pad" and math.isclose(s.x1, x, abs_tol=1e-3)
                   and math.isclose(s.y1, y, abs_tol=1e-3)]
        assert len(matches) == 1, (x, y)
        return matches[0]

    def pin_pad(self, header: str, pin: int) -> int:
        (x, y), = [key for key, value in self.header_pin.items() if value == (header, pin)]
        return self.pad_index(x, y)

    def resistor_pads(self) -> list[tuple[int, int]]:
        """(pad 1, pad 2) van elke weerstand: de gaten die geen headerpin zijn, twee aan twee boven elkaar."""
        others = [(round(x, 3), round(y, 3)) for x, y in self.lead_holes if (round(x, 3), round(y, 3)) not in self.header_pin]
        pairs = []
        for x, y in sorted(others):
            partner = (x, round(y + R_PITCH, 3))
            if partner in others:
                pairs.append((self.pad_index(x, y), self.pad_index(*partner)))
        return pairs


@pytest.fixture(scope="module")
def board() -> Board:
    return Board()


def pin_of_gpio(gpio: int) -> int:
    return HEADER_PIN[gpio]


# ---------------------------------------------------------------- de bestanden zelf

def test_the_committed_files_are_up_to_date():
    # pas hardware/gpio-adapter/maak_pcb.py aan en draai het opnieuw; de uitvoer wordt niet met de hand bewerkt
    assert maak_pcb.main(["--check"]) == 0


def test_the_zip_holds_exactly_the_gerber_and_drill_files():
    with zipfile.ZipFile(PCB / f"{NAME}-gerber.zip") as z:
        names = sorted(z.namelist())
        assert names == sorted(p.name for p in (PCB / "gerber").iterdir())
        for name in names:
            assert z.read(name).decode() == (PCB / "gerber" / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def test_it_is_a_single_layer_board(board):
    files = {p.name for p in (PCB / "gerber").iterdir()}
    assert files == {f"{NAME}-B_Cu.gbl", f"{NAME}-B_Mask.gbs", f"{NAME}-F_Silkscreen.gto", f"{NAME}-Edge_Cuts.gm1", f"{NAME}.drl"}
    kicad = (PCB / "kicad" / f"{NAME}.kicad_pcb").read_text(encoding="utf-8")
    assert '(layer "F.Cu")' not in re.sub(r'\(footprint "[^"]*" \(layer "F\.Cu"\)', "", kicad)  # alleen footprints staan 'boven'
    assert not re.search(r'\(pad [^\n]*"F\.Cu"', kicad) and "B.Cu" in kicad


# ---------------------------------------------------------------- verbindingen

def test_each_header_has_40_pins_and_there_are_26_resistors(board):
    assert len(board.header_pin) == 80 and len(board.resistor_pads()) == 26
    assert len(board.lead_holes) == 80 + 52 and len(board.mount_holes) == 4


def test_every_gpio_goes_through_one_resistor_to_the_same_pin_on_the_other_header(board):
    resistors = board.resistor_pads()
    for gpio in PINS:
        pin = pin_of_gpio(gpio)
        a, b = board.group_of[board.pin_pad("A", pin)], board.group_of[board.pin_pad("B", pin)]
        assert a != b, f"GPIO{gpio} (pin {pin}) is zonder weerstand doorverbonden"
        ends = [(r1, r2) for r1, r2 in resistors if board.group_of[r1] == a and board.group_of[r2] == b]
        assert len(ends) == 1, f"GPIO{gpio} (pin {pin}): verwacht precies één weerstand tussen A en B, kreeg {len(ends)}"
        # het koper van elke kant bevat verder niets: geen tweede pad, geen weerstand van een andere lijn
        for group in (a, b):
            pads = [i for i in board.groups[group] if board.copper[i].kind == "pad"]
            assert len(pads) == 2, f"GPIO{gpio}: {len(pads)} pads aan één stuk koper"


def test_the_ground_pins_are_connected_straight_through_and_to_nothing_else(board):
    for pin in GND_HEADER_PINS:
        a, b = board.group_of[board.pin_pad("A", pin)], board.group_of[board.pin_pad("B", pin)]
        assert a == b, f"GND-pin {pin} is niet doorverbonden"
        pads = [i for i in board.groups[a] if board.copper[i].kind == "pad"]
        assert len(pads) == 2, f"GND-pin {pin} hangt aan {len(pads) - 2} extra pad(s)"


def test_power_and_id_pins_are_not_connected_to_anything(board):
    for pin in sorted(POWER_HEADER_PINS | {27, 28}):
        for header in "AB":
            group = board.group_of[board.pin_pad(header, pin)]
            assert board.groups[group] == [board.pin_pad(header, pin)], f"pin {pin} van {header} heeft koper naar iets anders"


def test_no_two_nets_share_copper(board):
    # 26 GPIO-lijnen x 2 helften + 8 GND + 12 vrije pinnen per header
    expected = 26 * 2 + 8 + 2 * (40 - 26 - 8)
    assert len(board.groups) == expected, f"{len(board.groups)} koperdelen, verwacht {expected}: kortsluiting of losse baan"
    assert len(board.pads) == 80 + 52


def test_the_pin_table_matches_the_software(board):
    gpio_pins = {HEADER_PIN[g] for g in PINS}
    kinds = {pin: maak_pcb.pin_kind(pin) for pin in range(1, 41)}
    assert {p for p, k in kinds.items() if k == "gpio"} == gpio_pins
    assert {p for p, k in kinds.items() if k == "gnd"} == set(GND_HEADER_PINS)
    assert {p for p, k in kinds.items() if k == "power"} == set(POWER_HEADER_PINS)
    assert {p for p, k in kinds.items() if k == "id"} == {27, 28}


# ---------------------------------------------------------------- productieregels

def test_copper_of_different_nets_keeps_its_distance(board):
    worst = (1e9, None)
    for g1 in range(len(board.groups)):
        for g2 in range(g1 + 1, len(board.groups)):
            for i in board.groups[g1]:
                for j in board.groups[g2]:
                    value = gap(board.copper[i], board.copper[j])
                    if value < worst[0]:
                        worst = (value, (board.copper[i], board.copper[j]))
    assert worst[0] >= MIN_CLEARANCE, f"te dicht bij elkaar: {worst[0]:.3f} mm tussen {worst[1]}"


def test_tracks_pads_and_holes_have_workable_sizes(board):
    assert min(board.track_widths) >= MIN_TRACK, board.track_widths
    for pad in board.pads:
        hole = [d for x, y, d in board.holes if math.isclose(x, pad.x1, abs_tol=1e-3) and math.isclose(y, pad.y1, abs_tol=1e-3)]
        assert len(hole) == 1, "elke pad heeft precies één gat"
        size = 1.7 * (math.sqrt(2) if pad.square else 1)  # de omgeschreven cirkel van een vierkante pad is groter
        ring = (pad.r * 2 / (math.sqrt(2) if pad.square else 1) - hole[0]) / 2
        assert ring >= MIN_RING, f"te smalle kopering ({ring:.2f} mm) bij ({pad.x1:.2f}, {pad.y1:.2f}); {size}"


def test_every_hole_is_inside_the_board_and_copper_stays_off_the_edge(board):
    for x, y, d in board.holes:
        assert d / 2 + MIN_EDGE <= x <= board.width - d / 2 - MIN_EDGE and d / 2 + MIN_EDGE <= y <= board.height - d / 2 - MIN_EDGE
    for shape in board.copper:
        extent = shape.r
        for x, y in ((shape.x1, shape.y1), (shape.x2, shape.y2)):
            assert extent + MIN_EDGE <= x <= board.width - extent - MIN_EDGE, (x, y)
            assert extent + MIN_EDGE <= y <= board.height - extent - MIN_EDGE, (x, y)


def test_the_mounting_holes_do_not_touch_copper_or_the_headers(board):
    for x, y in board.mount_holes:
        hole = Shape(x, y, x, y, 1.6 + 1.5)  # gat plus ruimte voor de schroefkop
        assert all(gap(hole, s) > 0 for s in board.copper)


def test_the_solder_mask_opens_exactly_the_pads(board):
    assert len(board.mask) == len(board.pads)
    for x, y, kind, size in board.mask:
        pad = [p for p in board.pads if math.isclose(p.x1, x, abs_tol=1e-3) and math.isclose(p.y1, y, abs_tol=1e-3)]
        assert len(pad) == 1 and (kind == "R") == pad[0].square
        bigger = size[0] - (1.7 if kind == "R" else pad[0].r * 2)
        assert 0.05 <= bigger <= 0.2, "maskeropening hoort iets groter dan de pad te zijn"


def test_the_silkscreen_does_not_run_over_pads(board):
    for stroke in board.silk:
        for pad in board.pads:
            assert gap(stroke, pad) >= 0.1, f"zeefdruk raakt de pad op ({pad.x1:.2f}, {pad.y1:.2f})"


def test_resistor_bodies_fit_next_to_each_other_and_beside_the_headers(board):
    body_l, body_d = 6.3, 2.5
    bodies = []
    for p1, p2 in board.resistor_pads():
        a, b = board.copper[p1], board.copper[p2]
        assert math.isclose(a.x1, b.x1, abs_tol=1e-3)
        mid = (a.y1 + b.y1) / 2
        bodies.append((a.x1 - body_d / 2, mid - body_l / 2, a.x1 + body_d / 2, mid + body_l / 2))
    headers = []
    ys = sorted({round(y, 3) for (_x, y) in board.header_pin})
    for top in (ys[0], ys[2]):
        x_min = min(x for (x, y), (h, _p) in board.header_pin.items() if y == top)
        x_max = max(x for (x, y), (h, _p) in board.header_pin.items() if y == top)
        headers.append((x_min - PITCH, top + PITCH / 2 - 4.45, x_max + PITCH, top + PITCH / 2 + 4.45))

    def overlap(r1, r2, margin):
        return r1[0] < r2[2] + margin and r2[0] < r1[2] + margin and r1[1] < r2[3] + margin and r2[1] < r1[3] + margin

    for i, r1 in enumerate(bodies):
        assert not any(overlap(r1, r2, 0.3) for r2 in bodies[i + 1:]), f"weerstanden raken elkaar: {r1}"
        assert not any(overlap(r1, h, 0.3) for h in headers), f"weerstand tegen een header: {r1}"
    assert not overlap(headers[0], headers[1], 0.0)
    for h in headers:
        assert h[0] >= 0 and h[2] <= board.width and h[1] >= 0 and h[3] <= board.height


# ---------------------------------------------------------------- bij de rest van het project

def test_the_bill_of_materials_matches_the_design(board):
    rows = (PCB / "bom.csv").read_text(encoding="utf-8").splitlines()
    resistors = next(r for r in rows if "220 ohm" in r)
    assert resistors.startswith("26,") and all(f"R{g}" in resistors.split(",")[1].split() for g in PINS)
    assert any(r.startswith("2,J1 J2,2x20") for r in rows)


def test_the_kicad_file_is_balanced_and_matches_the_gerbers(board):
    text = (PCB / "kicad" / f"{NAME}.kicad_pcb").read_text(encoding="utf-8")
    depth = 0
    for char in re.sub(r'"[^"]*"', '""', text):
        depth += (char == "(") - (char == ")")
        assert depth >= 0
    assert depth == 0, "haakjes kloppen niet"
    assert text.count("(segment ") == len(board.tracks)
    assert text.count("(footprint ") == 2 + 26 + 4
    assert len(re.findall(r'\(pad "\d+" thru_hole', text)) == len(board.pads)
    assert text.count("(gr_line") >= 4  # de printrand


def test_the_documentation_describes_this_design():
    doc = (ROOT / "docs" / "pcb.md").read_text(encoding="utf-8")
    for needle in ("maak_pcb.py", "220", "1,27", "J1", "J2", f"{NAME}-gerber.zip", "B.Cu"):
        assert needle in doc, f"docs/pcb.md noemt {needle!r} niet"
    assert "pcb.md" in (ROOT / "docs" / "opstelling.md").read_text(encoding="utf-8")


def test_unknown_characters_are_refused_in_silkscreen_text():
    with pytest.raises(ValueError, match="zeefdruk"):
        maak_pcb.text_strokes("Q", 0, 0, 2)
