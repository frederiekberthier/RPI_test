"""Controleert dat de installatiescripts en diensten kloppen met de code. Echt draaien kan alleen op een Pi."""

import configparser
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
from bashutil import BASH

from rpitest import config
from rpitest.ui import server as ui_server

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "image"
INSTALL = ROOT / "install.sh"
SCRIPTS = sorted(IMAGE.glob("*.sh")) + [INSTALL]
UNITS = sorted((IMAGE / "systemd").glob("*.service"))


def read_unit(path):
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_expected_files_exist():
    assert {p.name for p in IMAGE.glob("*.sh")} == {"common.sh", "diagnose.sh", "kiosk.sh", "preflight.sh", "verify.sh"}
    assert INSTALL.is_file()  # het ene installatiescript staat in de hoofdmap
    assert not (IMAGE / "install-tester.sh").exists() and not (IMAGE / "install-dut.sh").exists()
    assert {p.name for p in UNITS} == {"rpitest-agent.service", "rpitest-ui.service"}


@pytest.mark.skipif(BASH is None, reason="geen werkende bash beschikbaar")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_have_valid_bash_syntax(script):
    result = subprocess.run([BASH, "-n", script.as_posix()], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_use_unix_line_endings(script):
    assert b"\r" not in script.read_bytes()  # CRLF laat bash op de Pi struikelen


def test_gitattributes_forces_lf_for_scripts_and_units():
    attributes = (ROOT / ".gitattributes").read_text()
    assert "*.sh text eol=lf" in attributes and "*.service text eol=lf" in attributes


def test_install_script_sources_common_and_guards_the_system():
    text = INSTALL.read_text(encoding="utf-8")
    assert "set -uo pipefail" in text  # geen -e: een mislukt onderdeel stopt de rest niet, het wordt gemeld
    assert 'image/common.sh"' in text
    assert "need_root" in text and "need_trixie" in text  # Bookworm heeft libgpiod 1.x


def test_ip_addresses_come_from_the_python_config_not_from_the_scripts():
    for script in SCRIPTS:
        assert "192.168." not in script.read_text(encoding="utf-8"), script.name
    text = INSTALL.read_text()
    assert "config_value SERVER_IP" in text and "config_value CLIENT_IP" in text
    assert hasattr(config, "SERVER_IP") and hasattr(config, "CLIENT_IP") and hasattr(config, "AGENT_PORT")


def test_every_file_the_install_script_installs_exists():
    text = INSTALL.read_text()
    units = re.findall(r"UNIT=(\S+\.service)", text)
    assert sorted(units) == sorted(p.name for p in UNITS)  # elke dienst hoort bij een rol
    for name in units:
        assert (IMAGE / "systemd" / name).is_file(), name
    assert "$IMAGE_DIR/kiosk.sh" in text and (IMAGE / "kiosk.sh").is_file()


def test_install_script_frees_the_gpio_pins_used_by_the_test():
    text = INSTALL.read_text()
    for step in ("do_i2c 1", "do_spi 1", "do_serial_hw 1", "do_serial_cons 1"):
        assert step in text


@pytest.mark.parametrize("unit", UNITS, ids=lambda p: p.name)
def test_units_are_well_formed_and_restart_automatically(unit):
    parsed = read_unit(unit)
    assert {"Unit", "Service", "Install"} <= set(parsed.sections())
    assert parsed["Service"]["Restart"] == "always"
    assert parsed["Install"]["WantedBy"] == "multi-user.target"  # start vanzelf bij het opstarten
    assert parsed["Service"]["ExecStart"].startswith("/opt/rpitest/venv/bin/python -m ")


def test_unit_modules_exist_and_options_are_accepted_by_the_cli():
    ui_unit = read_unit(IMAGE / "systemd" / "rpitest-ui.service")["Service"]["ExecStart"]
    agent_unit = read_unit(IMAGE / "systemd" / "rpitest-agent.service")["Service"]["ExecStart"]
    assert "-m rpitest.ui " in ui_unit + " " and "-m rpitest.agent" in agent_unit
    assert importlib.util.find_spec("rpitest.ui.__main__") and importlib.util.find_spec("rpitest.agent.__main__")
    help_text = subprocess.run([sys.executable, "-m", "rpitest.ui", "--help"], capture_output=True, text=True,
                               cwd=ROOT).stdout
    for flag in re.findall(r"(--[a-z-]+)", ui_unit):
        assert flag in help_text, flag  # een dienst met een onbekende optie start nooit


def test_paths_in_units_match_the_install_script():
    common = (IMAGE / "common.sh").read_text()
    assert 'APP_DIR="${APP_DIR:-/opt/rpitest}"' in common and 'VENV="$APP_DIR/venv"' in common
    assert 'DATA_DIR="${DATA_DIR:-/var/lib/rpitest}"' in common
    ui_unit = read_unit(IMAGE / "systemd" / "rpitest-ui.service")["Service"]
    assert "/var/lib/rpitest/reports" in ui_unit["ExecStart"] and ui_unit["WorkingDirectory"] == "/var/lib/rpitest"


def test_kiosk_url_matches_the_ui_port_and_restarts_the_browser():
    kiosk = (IMAGE / "kiosk.sh").read_text()
    assert f"127.0.0.1:{ui_server.DEFAULT_PORT}" in kiosk
    assert "--kiosk" in kiosk and "while true" in kiosk and "curl" in kiosk


def test_ui_binds_locally_by_default():
    # de TEST-SERVER opent tijdens de wifi-test een hotspot: de startknop mag daar niet bereikbaar zijn
    unit = read_unit(IMAGE / "systemd" / "rpitest-ui.service")["Service"]["ExecStart"]
    assert "--host" not in unit
    help_text = subprocess.run([sys.executable, "-m", "rpitest.ui", "--help"], capture_output=True, text=True,
                               cwd=ROOT).stdout
    assert "enkel lokaal" in help_text


# ---------------------------------------------------------------- voorcontrole, natest en diagnose

READ_ONLY_SCRIPTS = ["preflight.sh", "verify.sh", "diagnose.sh"]
FORBIDDEN = [
    r"\brm\b", r"\bapt(?:-get)?\b", r"\bpip\b", r"systemctl\s+(?:restart|start|stop|enable|disable|daemon-reload|mask)",
    r"nmcli\s+(?:\S+\s+)*(?:add|modify|delete|up|down)\b", r"raspi-config\s+nonint", r"\breboot\b", r"\bpoweroff\b",
    r"\bdd\b", r"--show-secrets", r"\bmkfs", r"\bchmod\b", r"\bchown\b", r"hostnamectl", r"rfkill\s+(?:un)?block",
    r">\s*/(?:etc|boot|sys|var/lib)", r"\binstall\s+-",
]


def code_lines(path):
    """De regels zonder volledige commentaarregels."""
    return [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]


@pytest.mark.parametrize("name", READ_ONLY_SCRIPTS)
def test_check_scripts_never_modify_the_system(name):
    for line in code_lines(IMAGE / name):
        for pattern in FORBIDDEN:
            assert not re.search(pattern, line), f"{name}: verboden opdracht {pattern!r} in: {line.strip()}"


def test_forbidden_patterns_actually_catch_what_they_should():
    for bad in ["sudo rm -rf x", "apt-get install foo", "nmcli connection delete rpitest",
                "nmcli con up rpitest", "systemctl restart rpitest-ui", "raspi-config nonint do_i2c 1",
                "echo x > /etc/hosts", "dd if=/dev/zero of=/dev/sda"]:
        assert any(re.search(p, bad) for p in FORBIDDEN), bad
    for fine in ["nmcli -t -f NAME connection show", "nmcli dev wifi list --rescan yes",
                 "systemctl is-active --quiet x", "journalctl -u rpitest-ui -n 80 --no-pager"]:
        assert not any(re.search(p, fine) for p in FORBIDDEN), fine


def test_install_script_runs_the_preflight_before_changing_anything():
    text = INSTALL.read_text(encoding="utf-8")
    assert "preflight.sh" in text and "SKIP_PREFLIGHT" in text and "--skip-preflight" in text
    assert text.index("preflight.sh") < text.rindex('"apply_$component"')  # vóór de eerste wijziging
    assert text.index("preflight.sh") > text.index("CHECK_ONLY\" -eq 1 ]; then")  # en niet in --check


def test_preflight_and_verify_know_the_roles():
    for name in ("preflight.sh", "verify.sh"):
        text = (IMAGE / name).read_text(encoding="utf-8")
        assert 'need_role "$ROLE"' in text and "finish_checks" in text
    assert "server" in (IMAGE / "preflight.sh").read_text() and "labwc" in (IMAGE / "preflight.sh").read_text()


def test_verify_matches_the_code_it_checks():
    text = (IMAGE / "verify.sh").read_text(encoding="utf-8")
    assert f"UI_PORT={ui_server.DEFAULT_PORT}" in text
    from rpitest.gpio.real import HEADER_CHIP_LABELS
    for label in HEADER_CHIP_LABELS:
        assert label.removeprefix("pinctrl-") in text, label  # rp1, bcm2711, bcm2835
    assert "rpitest-ui.service" in text and "rpitest-agent.service" in text
    for unit in UNITS:
        assert unit.name in text


def test_diagnose_runs_the_same_commands_the_tests_parse():
    text = (IMAGE / "diagnose.sh").read_text(encoding="utf-8")
    assert "SSID,SIGNAL,FREQ,BSSID" in text  # de velden van wifi_scan
    assert "config_value BT_SCAN_SECONDS" in text and 'bluetoothctl --timeout "$BT_SECONDS" scan on' in text  # één bron voor de duur
    for command in ("vcgencmd get_throttled", "vcgencmd pmic_read_adc", "bluetoothctl show", "iw reg get",
                    "ping -c 3 -i 0.2 -q -W 1", "lsblk", "ls -l /sys/block/", "dmesg", "--list-chips",
                    "/sys/class/thermal/thermal_zone0/temp", "journalctl -u rpitest-ui"):
        assert command in text, command
