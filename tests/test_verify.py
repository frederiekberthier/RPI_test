"""image/verify.sh (de natest) tegen nagebootste systeemopdrachten, na een installatie in de Sandbox."""

import pytest
from bashutil import BASH
from test_install_script import Sandbox

pytestmark = pytest.mark.skipif(BASH is None, reason="geen werkende bash beschikbaar")

SERVER_IP = "192.168.77.1"
CLIENT_IP = "192.168.77.2"


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def installed(box, role, with_cable=True, **sysroot):
    """Installeer in de Sandbox en maak een nagebootste /sys, /dev en /boot; met kabel heeft de poort het testadres."""
    result = box.run(role, "--skip-preflight")
    assert result.returncode == 0, result.clean
    box.make_sysroot(**sysroot)
    for tool in ("iperf3", "iw", "bluetoothctl", "vcgencmd"):
        box.add_stub(tool)
    if with_cable:
        ip = SERVER_IP if role == "server" else CLIENT_IP
        (box.state / "eth_ip").write_text(f"2: eth0    inet {ip}/24 brd 192.168.77.255 scope global eth0\n")
    return box


def verify(box, role, **env):
    return box.run_script("image/verify.sh", role, KIOSK_USER="kiosk", BROWSER_RUNNING="1", **env)


def test_a_healthy_server_passes_and_changes_nothing(box):
    installed(box, "server")
    before = len(box.mutations())
    result = verify(box, "server")
    assert result.returncode == 0, result.clean
    assert "Geen fouten" in result.clean and "[FOUT]" not in result.clean
    assert len(box.mutations()) == before  # de natest wijzigt niets


def test_a_healthy_client_passes(box):
    installed(box, "client")
    result = verify(box, "client")
    assert result.returncode == 0, result.clean
    assert "rpitest-agent.service draait" in result.clean and "de agent antwoordt" in result.clean


def test_a_client_without_the_test_cable_only_gets_notes(box):
    # issue #22: zonder kabel bestaat het testadres niet en de agent wacht; dat is geen fout
    installed(box, "client", with_cable=False)
    result = verify(box, "client", FAIL_AGENT="1")
    assert result.returncode == 0, result.clean
    assert "[FOUT]" not in result.clean
    assert "heeft 192.168.77.2 niet" in result.clean and "de agent antwoordt niet" in result.clean


def test_a_service_that_is_not_running_is_an_error(box):
    installed(box, "server")
    (box.state / "enabled_rpitest-ui.service").unlink()
    result = verify(box, "server")
    assert result.returncode == 1 and "[FOUT]" in result.clean and "rpitest-ui.service" in result.clean


@pytest.mark.parametrize("sysroot,expected", [
    ({"i2c": True}, "I2C staat aan"),
    ({"spi": True}, "SPI staat aan"),
    ({"serial_console": True}, "seriële console staat aan"),
])
def test_pins_that_are_still_claimed_are_errors(box, sysroot, expected):
    installed(box, "server", **sysroot)
    result = verify(box, "server")
    assert result.returncode == 1 and expected in result.clean, result.clean


def test_a_screen_service_that_does_not_answer_is_an_error(box):
    installed(box, "server")
    result = verify(box, "server", FAIL_UI="1")
    assert result.returncode == 1 and "de webpagina antwoordt niet" in result.clean


def test_a_broken_python_environment_is_an_error(box):
    installed(box, "server")
    (box.state / "import_broken").write_text("x")
    result = verify(box, "server")
    assert result.returncode == 1 and "niet te importeren" in result.clean


def test_a_missing_network_profile_and_a_missing_autostart_are_errors(box):
    installed(box, "server")
    (box.state / "nm_profile").unlink()
    (box.root / "home" / ".config" / "labwc" / "autostart").unlink()
    result = verify(box, "server")
    assert result.returncode == 1
    assert "NetworkManager-profiel 'rpitest' ontbreekt" in result.clean and "autostart van de kioskbrowser ontbreekt" in result.clean


def test_a_browser_that_is_not_running_is_only_a_note(box):
    installed(box, "server")
    result = box.run_script("image/verify.sh", "server", KIOSK_USER="kiosk", BROWSER_RUNNING="0")
    assert result.returncode == 0 and "de kioskbrowser draait niet" in result.clean


# ---------------------------------------------------------------- issue #30: importeer niet vanuit de repomap

def test_the_python_checks_run_isolated_so_the_checkout_cannot_hide_a_missing_install(box):
    installed(box, "server")
    verify(box, "server")
    calls = box.calls()
    assert "venv-python -I -c import rpitest, gpiod" in calls
    assert "venv-python -I -m rpitest.agent --list-chips" in calls
    # ook de controles van install.sh zelf (check_app en apply_app)
    assert not [c for c in calls if c.startswith("venv-python -c import rpitest")]


def test_verify_needs_root_and_a_valid_role(box):
    installed(box, "server")
    assert "sudo" in box.run_script("image/verify.sh", "server", FAKE_UID="1000").clean
    assert "gebruik:" in box.run_script("image/verify.sh", "tester").clean


# ---------------------------------------------------------------- diagnose.sh: echte uitvoer, geen geheimen

def test_diagnose_collects_output_but_never_asks_for_secrets(box):
    # nmcli geeft alleen een wachtwoord als erom gevraagd wordt (--show-secrets of -s); de stub verraadt dat
    box.add_stub("nmcli", 'echo "nmcli $*" >> "$STATE/calls"\n'
                 'case "$*" in *show-secrets*|*" -s "*|*802-11-wireless-security*) echo "psk=GEHEIM-WACHTWOORD";; esac\n'
                 'echo "wifi-lijst"')
    box.add_stub("bluetoothctl", 'echo "bluetoothctl $*" >> "$STATE/calls"\necho "Controller AA:BB"')
    out = box.root / "diagnose.txt"
    result = box.run_script("image/diagnose.sh", out.as_posix())
    assert result.returncode == 0, result.clean
    text = out.read_text(encoding="utf-8", errors="replace")
    assert "Klaar. Dit bestand staat in" in text and "wifi-lijst" in text and "Controller AA:BB" in text
    assert "GEHEIM-WACHTWOORD" not in result.clean + text
    asked = [c for c in box.calls() if c.startswith(("nmcli", "bluetoothctl"))]
    assert asked and not [c for c in asked if "secret" in c or "password" in c.lower()]
    assert [c for c in box.mutations() if c != "rfkill list"] == []  # de diagnose wijzigt niets (rfkill list leest alleen)


# ---------------------------------------------------------------- kiosk.sh: 'Afsluiten > Applicatie sluiten'

def run_kiosk(box, chromium_body, **env):
    box.add_stub("chromium", 'echo "chromium $*" >> "$STATE/calls"\n' + chromium_body)
    box.add_stub("sleep", "exit 0")
    flag = box.root / "kiosk-exit"
    result = box.run_script("image/kiosk.sh", RPITEST_EXIT_FLAG=flag.as_posix(), **env)
    return result, flag


def test_the_kiosk_browser_is_restarted_when_it_stops_on_its_own(box):
    # de stub zet het vlag pas bij de derde start: tot dan hoort de browser telkens herstart te worden
    result, _ = run_kiosk(box, 'n=$(grep -c "^chromium" "$STATE/calls"); [ "$n" -ge 3 ] && touch "$RPITEST_EXIT_FLAG"; exit 0')
    assert result.returncode == 0, result.clean
    assert len([c for c in box.calls() if c.startswith("chromium")]) == 3  # na elke stop opnieuw gestart


def test_the_kiosk_stays_closed_once_the_exit_flag_exists(box):
    result, flag = run_kiosk(box, 'touch "$RPITEST_EXIT_FLAG"; exit 0')
    assert result.returncode == 0 and flag.exists()
    assert len([c for c in box.calls() if c.startswith("chromium")]) == 1  # één keer gestart, daarna niet herstart


def test_the_kiosk_does_not_even_wait_for_the_service_when_it_was_closed_on_purpose(box):
    box.add_stub("curl", "exit 22")  # de webdienst is al gestopt
    (box.root / "kiosk-exit").write_text("1")
    result, _ = run_kiosk(box, "exit 0")
    assert result.returncode == 0
    assert not [c for c in box.calls() if c.startswith("chromium")]
