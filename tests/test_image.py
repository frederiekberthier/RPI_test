"""Controleert dat de installatiescripts en diensten kloppen met de code. Echt draaien kan alleen op een Pi."""

import configparser
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from rpitest import config
from rpitest.ui import server as ui_server

ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "image"
SCRIPTS = sorted(IMAGE.glob("*.sh"))
UNITS = sorted((IMAGE / "systemd").glob("*.service"))


def read_unit(path):
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_expected_files_exist():
    assert {p.name for p in SCRIPTS} == {"common.sh", "install-dut.sh", "install-tester.sh", "kiosk.sh"}
    assert {p.name for p in UNITS} == {"rpitest-agent.service", "rpitest-ui.service"}


def working_bash():
    """Een bash die echt werkt. Op Windows is `bash` vaak de WSL-starter zonder distributie: die telt niet."""
    candidates = [shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]
    for candidate in filter(None, candidates):
        try:
            probe = subprocess.run([candidate, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.stdout.strip() == "ok":
            return candidate
    return None


BASH = working_bash()


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


@pytest.mark.parametrize("script", [IMAGE / "install-tester.sh", IMAGE / "install-dut.sh"], ids=lambda p: p.name)
def test_install_scripts_are_safe_and_source_common(script):
    text = script.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert 'common.sh"' in text
    assert "need_root" in text and "need_trixie" in text  # Bookworm heeft libgpiod 1.x


def test_ip_addresses_come_from_the_python_config_not_from_the_scripts():
    for script in SCRIPTS:
        assert "192.168." not in script.read_text(encoding="utf-8"), script.name
    text = (IMAGE / "install-tester.sh").read_text() + (IMAGE / "install-dut.sh").read_text()
    assert "config_value TESTER_IP" in text and "config_value DUT_IP" in text
    assert hasattr(config, "TESTER_IP") and hasattr(config, "DUT_IP") and hasattr(config, "AGENT_PORT")


def test_every_file_the_scripts_install_exists():
    text = (IMAGE / "common.sh").read_text() + (IMAGE / "install-tester.sh").read_text()
    for name in re.findall(r"install_unit (\S+\.service)", (IMAGE / "install-tester.sh").read_text()
                           + (IMAGE / "install-dut.sh").read_text()):
        assert (IMAGE / "systemd" / name).is_file(), name
    assert "kiosk.sh" in text and (IMAGE / "kiosk.sh").is_file()


def test_tester_script_frees_the_gpio_pins_used_by_the_test():
    text = (IMAGE / "common.sh").read_text()
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
    help_text = subprocess.run(["python", "-m", "rpitest.ui", "--help"], capture_output=True, text=True,
                               cwd=ROOT).stdout
    for flag in re.findall(r"(--[a-z-]+)", ui_unit):
        assert flag in help_text, flag  # een dienst met een onbekende optie start nooit


def test_paths_in_units_match_the_install_script():
    common = (IMAGE / "common.sh").read_text()
    assert "APP_DIR=/opt/rpitest" in common and 'VENV="$APP_DIR/venv"' in common
    assert "DATA_DIR=/var/lib/rpitest" in common
    ui_unit = read_unit(IMAGE / "systemd" / "rpitest-ui.service")["Service"]
    assert "/var/lib/rpitest/reports" in ui_unit["ExecStart"] and ui_unit["WorkingDirectory"] == "/var/lib/rpitest"


def test_kiosk_url_matches_the_ui_port_and_restarts_the_browser():
    kiosk = (IMAGE / "kiosk.sh").read_text()
    assert f"127.0.0.1:{ui_server.DEFAULT_PORT}" in kiosk
    assert "--kiosk" in kiosk and "while true" in kiosk and "curl" in kiosk


def test_ui_binds_locally_by_default():
    # de testpi opent tijdens de wifi-test een hotspot: de startknop mag daar niet bereikbaar zijn
    unit = read_unit(IMAGE / "systemd" / "rpitest-ui.service")["Service"]["ExecStart"]
    assert "--host" not in unit
    help_text = subprocess.run(["python", "-m", "rpitest.ui", "--help"], capture_output=True, text=True,
                               cwd=ROOT).stdout
    assert "enkel lokaal" in help_text
