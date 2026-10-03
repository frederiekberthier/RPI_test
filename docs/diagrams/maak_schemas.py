"""Genereert de schema's in docs/img/ (SVG).

    pip install matplotlib
    python docs/diagrams/maak_schemas.py              # schrijft docs/img/*.svg
    python docs/diagrams/maak_schemas.py --png DIR    # schrijft er ook PNG's naar DIR (om te bekijken)

De pinindeling komt uit rpitest.gpio.ports, zodat tekening en code niet uit elkaar kunnen lopen.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["svg.hashsalt"] = "rpitest"  # vaste ID's: een nieuwe run geeft geen ruis in git
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from rpitest.gpio.ports import GND_HEADER_PINS, HEADER_PIN, POWER_HEADER_PINS  # noqa: E402

BLUE, BLACK, RED, GREY, GREEN, PURPLE = "#1f6fb4", "#222222", "#c62828", "#8d8d8d", "#2e7d4f", "#7b3fa0"
BOARD, BOARD_EDGE, HOLE = "#f1e9d2", "#b9ab86", "#8a7f63"
INK = "#1c1c1c"

PIN_BY_HEADER = {v: k for k, v in HEADER_PIN.items()}
CABLE_GND = (6, 14, 39)  # de drie GND-draden zonder weerstand


def pin_info(n: int) -> tuple[str, str]:
    """(label, soort) van fysieke pin n: soort is gpio, gnd, power of id."""
    if n in GND_HEADER_PINS:
        return "GND", "gnd"
    if n in POWER_HEADER_PINS:
        return ("3V3" if n in (1, 17) else "5V"), "power"
    if n in (27, 28):
        return ("ID_SD" if n == 27 else "ID_SC"), "id"
    return f"GPIO{PIN_BY_HEADER[n]}", "gpio"


def has_cable(n: int) -> bool:
    return pin_info(n)[1] == "gpio" or n in CABLE_GND


def _check_pin_table() -> None:
    kinds = [pin_info(n)[1] for n in range(1, 41)]
    assert (kinds.count("gpio"), kinds.count("gnd"), kinds.count("power"), kinds.count("id")) == (26, 8, 4, 2)


# ---------------------------------------------------------------- breadboard

P, Q = 0.30, 0.55  # gatafstand (x) en rijafstand (y)
ROWS = 20


def draw_board(ax, cx: float, top: float, title: str) -> None:
    half = 6.2 * P
    bottom = top - (ROWS - 1) * Q
    ax.add_patch(FancyBboxPatch((cx - half, bottom - 0.45), 2 * half, top - bottom + 0.9,
                                boxstyle="round,pad=0,rounding_size=0.15", fc=BOARD, ec=BOARD_EDGE, lw=1.2))
    ax.add_patch(Rectangle((cx - 0.5 * P, bottom - 0.45), P, top - bottom + 0.9, fc="#ddd2b1", ec="none"))
    ax.text(cx, top + 0.95, title, ha="center", va="bottom", fontsize=12, fontweight="bold", color=INK)
    ax.text(cx, top + 0.6, "breadboard met 40-pins breakout, pin 1 linksboven", ha="center", va="bottom",
            fontsize=8.5, color="#555")
    ax.add_patch(Rectangle((cx - 2.0 * P, bottom - 0.3), 4.0 * P, top - bottom + 0.6, fc="#2e7d4f", ec="#1c5a37",
                           alpha=0.85, zorder=2))

    for row in range(ROWS):
        y = top - row * Q
        for side, pin in ((-1, 2 * row + 1), (1, 2 * row + 2)):
            label, kind = pin_info(pin)
            for hole in (2.5, 3.5, 4.5, 5.5):  # vrije gaten a-d resp. g-j
                ax.add_patch(Circle((cx + side * hole * P, y), 0.045, fc=HOLE, ec="none", zorder=1))
            colour = {"gpio": BLUE, "gnd": BLACK, "power": RED, "id": GREY}[kind]
            marker = {"gpio": "o", "gnd": "s", "power": "^", "id": "D"}[kind]
            ax.plot(cx + side * 1.5 * P, y, marker, ms=6.5, color=colour, mec="white", mew=0.8, zorder=3)

            edge = cx + side * 6.2 * P
            tx = edge + side * 0.4
            ha = "left" if side > 0 else "right"
            name = f"{label} ({pin})"
            if has_cable(pin):
                plug = cx + side * 3.5 * P
                ax.plot([plug, edge + side * 0.3], [y, y], "-", color=colour, lw=2.4, zorder=4, solid_capstyle="round")
                ax.add_patch(Circle((plug, y), 0.06, fc=colour, ec="white", lw=0.8, zorder=5))
                ax.text(tx, y, name, ha=ha, va="center", fontsize=9, color=INK)
            elif kind == "power":
                ax.text(tx, y, f"{name}  ✕ niet verbinden", ha=ha, va="center", fontsize=8.5,
                        color=RED, fontweight="bold")
            else:
                note = "niet gebruikt" if kind == "id" else "vrij"
                ax.text(tx, y, f"{name}  {note}", ha=ha, va="center", fontsize=8.5, color=GREY)


def draw_cable_inset(ax, x0: float, y: float) -> None:
    """Een weerstandskabel: dupontdraad met een weerstand van 220 ohm er middenin."""
    ax.text(x0, y + 1.25, "Eén weerstandskabel (26 stuks voor de GPIO's, plus 3 gewone draden voor GND)",
            fontsize=10.5, fontweight="bold", color=INK, va="bottom")
    ax.add_patch(Rectangle((x0, y - 0.07), 5.2, 0.14, fc=BLUE, ec="none"))
    ax.add_patch(Rectangle((x0 + 8.8, y - 0.07), 5.2, 0.14, fc=BLUE, ec="none"))
    for xa, xb in ((x0 - 0.5, x0), (x0 + 14.0, x0 + 14.5)):
        ax.add_patch(Rectangle((xa, y - 0.1), xb - xa, 0.2, fc="#b9b9b9", ec="#777", lw=0.8))  # pennetje
    ax.add_patch(FancyBboxPatch((x0 + 5.0, y - 0.38), 4.2, 0.76, boxstyle="round,pad=0,rounding_size=0.2",
                                fc="#e8e0cf", ec="#555", lw=1))  # weerstand
    for dx, colour in ((5.9, "#c62828"), (6.5, "#c62828"), (7.1, "#7b4a1f"), (7.9, "#d4af37")):
        ax.add_patch(Rectangle((x0 + dx, y - 0.38), 0.3, 0.76, fc=colour, ec="none"))
    ax.add_patch(Rectangle((x0 + 4.6, y - 0.52), 5.0, 1.04, fc="none", ec="#999", ls="--", lw=1))  # krimpkous
    ax.text(x0 + 7.1, y - 0.75, "weerstand 220 Ω (rood-rood-bruin-goud)\nin krimpkous", ha="center", va="top",
            fontsize=8.5, color="#444")
    ax.text(x0 - 0.5, y - 0.75, "pennetje in breakout A\n(testpi)", ha="left", va="top", fontsize=8.5, color="#444")
    ax.text(x0 + 14.5, y - 0.75, "pennetje in breakout B\n(DUT)", ha="right", va="top", fontsize=8.5, color="#444")


def breadboard_figure():
    fig, ax = plt.subplots(figsize=(13, 10))
    top = 13.2
    draw_board(ax, 7.0, top, "A – testpi")
    draw_board(ax, 24.6, top, "B – DUT (te testen Pi)")

    # bundel in het midden
    mid = 15.8
    ax.add_patch(FancyArrowPatch((13.7, top - 4.7), (17.9, top - 4.7), arrowstyle="<->", mutation_scale=22,
                                 lw=5, color=BLUE, zorder=1))
    ax.text(mid, top - 3.55, "pin n op A  ↔  pin n op B", ha="center", fontsize=11.5, fontweight="bold", color=INK)
    ax.text(mid, top - 5.35, "26 × weerstandskabel 220 Ω\n(alle blauwe GPIO's, ●)\n\n"
            "3 × gewone draad zonder weerstand\n(GND: pin 6, 14 en 39, ■)\n\n"
            "Elke draad gaat naar dezelfde pin\nop de andere breakout.", ha="center", va="top", fontsize=9.5, color=INK,
            linespacing=1.25)

    legend_y = 1.0
    items = [("o", BLUE, "GPIO (verbinden)"), ("s", BLACK, "GND (alleen pin 6, 14, 39 verbinden)"),
             ("^", RED, "3V3 / 5V (nooit verbinden)"), ("D", GREY, "ID-pinnen (niet gebruikt)")]
    x = 3.0
    for marker, colour, text in items:
        ax.plot(x, legend_y, marker, ms=8, color=colour, mec="white", mew=0.8)
        ax.text(x + 0.45, legend_y, text, va="center", fontsize=9, color=INK)
        x += 1.6 + 0.19 * len(text)
    draw_cable_inset(ax, 8.6, -2.6)
    ax.text(15.8, -5.4, "Beide Pi's zijn uit tijdens het aansteken. Elke Pi heeft zijn eigen voeding; de enige "
            "gemeenschappelijke verbinding is GND.", ha="center", fontsize=9, color="#555")

    ax.set_xlim(0, 32.5)
    ax.set_ylim(-5.9, top + 2.4)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig


# ---------------------------------------------------------------- overzicht

def box(ax, x, y, w, h, title, lines, colour):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.3", fc="#f6f6f4",
                                ec=colour, lw=2.2))
    ax.text(x + w / 2, y + h - 0.45, title, ha="center", va="top", fontsize=12.5, fontweight="bold", color=INK)
    ax.text(x + w / 2, y + h - 1.35, "\n".join(lines), ha="center", va="top", fontsize=9.5, color="#333",
            linespacing=1.35)


def link(ax, y, colour, label, sub="", style="-", lw=4, x0=8.4, x1=15.6):
    ax.add_patch(FancyArrowPatch((x0, y), (x1, y), arrowstyle="<->", mutation_scale=18, lw=lw, color=colour,
                                 linestyle=style))
    ax.text((x0 + x1) / 2, y + 0.3, label, ha="center", va="bottom", fontsize=10, fontweight="bold", color=INK)
    if sub:
        ax.text((x0 + x1) / 2, y - 0.3, sub, ha="center", va="top", fontsize=8.8, color="#444")


def overview_figure():
    fig, ax = plt.subplots(figsize=(12, 7.4))
    box(ax, 0.6, 3.0, 7.8, 7.0, "Testpi (Pi 5)",
        ["stuurt de tests aan", "maakt het rapport (JSON + HTML)", "", "eigen GPIO (breakout A)",
         "ethernet 192.168.77.1: ping, iperf3", "wifi: accesspoint", "bluetooth: zichtbaar + scannen"], BLUE)
    box(ax, 15.6, 3.0, 7.8, 7.0, "Te testen Pi (Pi 4/5)",
        ["draait de agent (tester-SD)", "voert opdrachten uit, beslist niets", "", "onder test:",
         "GPIO (breakout B)  ·  ethernet 192.168.77.2", "wifi  ·  bluetooth  ·  4 USB-A-poorten",
         "voeding  ·  temperatuur  ·  CPU  ·  RAM"], GREEN)

    link(ax, 9.0, BLUE, "GPIO 2–27 + 3× GND", "via 220 Ω (zie breadboard-schema)")
    link(ax, 7.2, "#2a7f2a", "Ethernet", "UTP-kabel, 1 Gb/s: link, ping, iperf3")
    link(ax, 5.4, PURPLE, "Wifi 2,4 + 5 GHz", "testpi = accesspoint, DUT verbindt", style=(0, (4, 3)), lw=3)
    link(ax, 3.7, PURPLE, "Bluetooth", "beide richtingen zichtbaar", style=(0, (1, 2)), lw=3)

    # scherm en voedingen
    ax.add_patch(Rectangle((1.6, 11.3), 5.8, 2.0, fc="#222", ec="#000", lw=1.5))
    ax.text(4.5, 12.3, "scherm met rapport", ha="center", va="center", color="white", fontsize=10.5)
    ax.plot([4.5, 4.5], [10.0, 11.3], "-", color=INK, lw=2)
    ax.text(4.8, 10.65, "HDMI", fontsize=9, va="center", color="#444")
    for x, y_box, y_from, y_to in ((4.5, 0.7, 1.7, 3.0), (19.5, 11.3, 11.3, 10.0)):
        ax.add_patch(Rectangle((x - 1.4, y_box), 2.8, 1.0, fc="#fff6d6", ec="#b8962e", lw=1.2))
        ax.text(x, y_box + 0.5, "eigen voeding", ha="center", va="center", fontsize=9, color=INK)
        ax.plot([x, x], [y_from, y_to], "-", color="#b8962e", lw=2)

    # USB-fixture onder de DUT
    ax.plot([19.5, 19.5], [3.0, 2.4], "-", color=INK, lw=2)
    ax.text(19.8, 2.7, "USB", fontsize=9, va="center", color="#444")
    for i, label in enumerate(("SLOT1\nUSB 3", "SLOT2\nUSB 3", "SLOT3\nUSB 2", "SLOT4\nUSB 2")):
        ax.add_patch(Rectangle((15.6 + i * 2.0, 0.5), 1.8, 1.7, fc="#e8eef6", ec="#456", lw=1.2))
        ax.text(15.6 + i * 2.0 + 0.9, 1.35, label, ha="center", va="center", fontsize=8.5, color=INK)
    ax.text(15.6, 0.1, "USB-fixture: 4 voorbereide teststicks", fontsize=8.5, color="#444", va="top")

    ax.set_xlim(0, 24)
    ax.set_ylim(-0.6, 13.8)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
    return fig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--png", type=Path, help="schrijf ook PNG's naar deze map")
    args = parser.parse_args()
    _check_pin_table()
    out = ROOT / "docs" / "img"
    out.mkdir(parents=True, exist_ok=True)
    for name, make in (("overzicht", overview_figure), ("breadboard", breadboard_figure)):
        fig = make()
        fig.savefig(out / f"{name}.svg", format="svg", metadata={"Date": None})
        if args.png:
            args.png.mkdir(parents=True, exist_ok=True)
            fig.savefig(args.png / f"{name}.png", dpi=110)
        plt.close(fig)
        print(f"docs/img/{name}.svg")


if __name__ == "__main__":
    main()
