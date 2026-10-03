"""image/preflight.sh tegen nagebootste systeemopdrachten en een nagebootste /sys, /proc, /dev (zie Sandbox)."""

import os
import re
import shutil

import pytest
from bashutil import BASH
from test_install_script import Sandbox

pytestmark = pytest.mark.skipif(BASH is None, reason="geen werkende bash beschikbaar")


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def healthy_server(box, **sysroot):
    box.make_sysroot(**sysroot)
    box.add_stub("labwc")
    return box


def preflight(box, role="server", **env):
    return box.run_script("image/preflight.sh", role, KIOSK_USER="kiosk", **env)


def test_a_healthy_server_passes_and_changes_nothing(box):
    result = preflight(healthy_server(box))
    assert result.returncode == 0, result.clean
    assert "Geen fouten" in result.clean and "[FOUT]" not in result.clean
    assert box.mutations() == []  # de voorcontrole wijzigt niets


def test_a_healthy_client_needs_no_desktop(box):
    box.make_sysroot(model="Raspberry Pi 4 Model B Rev 1.5")
    result = preflight(box, "client")
    assert result.returncode == 0, result.clean
    assert "labwc" not in result.clean and "model: Raspberry Pi 4" in result.clean


def test_no_internet_is_an_error_for_both_package_sources(box):
    result = preflight(healthy_server(box), FAIL_HTTP="1")
    assert result.returncode == 1
    assert result.clean.count("niet bereikbaar") == 2
    assert "deb.debian.org" in result.clean and "archive.raspberrypi.com" in result.clean


def test_a_missing_desktop_is_an_error_for_the_server_only(box):
    box.make_sysroot()
    server = preflight(box)
    assert server.returncode == 1 and "labwc ontbreekt" in server.clean
    assert preflight(box, "client").returncode == 0


def test_a_missing_ethernet_port_names_the_expected_interface(box):
    result = preflight(healthy_server(box, eth=None))
    assert result.returncode == 1 and "ethernetpoort eth0 niet gevonden" in result.clean
    other = preflight(healthy_server(box, eth="enp3s0"), ETH_IFACE="enp3s0")
    assert other.returncode == 0, other.clean


def test_a_missing_screen_wifi_or_bluetooth_are_warnings_not_errors(box):
    result = preflight(healthy_server(box, hdmi=False, wifi=False, bluetooth=False))
    assert result.returncode == 0, result.clean
    for text in ("geen scherm op HDMI", "geen wifi-interface", "geen bluetooth-controller"):
        assert text in result.clean, text


def test_anything_but_trixie_is_refused(box):
    (box.root / "os-release").write_text("VERSION_CODENAME=bookworm\n")
    result = preflight(healthy_server(box))
    assert result.returncode == 1 and "Trixie is nodig" in result.clean


def test_the_wrong_model_is_only_a_note(box):
    result = preflight(healthy_server(box, model="Raspberry Pi 4 Model B Rev 1.5"))
    assert result.returncode == 0 and "hoort een Pi 5 te zijn" in result.clean


def test_a_session_over_the_test_cable_port_is_warned_about(box):
    healthy_server(box)
    over_cable = preflight(box, SSH_CONNECTION="10.0.0.9 5000 10.0.0.1 22", ROUTE_DEV="eth0")
    assert "je bent via eth0 verbonden" in over_cable.clean and "verbreekt deze sessie" in over_cable.clean
    over_wifi = preflight(box, SSH_CONNECTION="10.0.0.9 5000 10.0.0.1 22", ROUTE_DEV="wlan0")
    assert "verbreekt deze sessie" not in over_wifi.clean and "loopt via wlan0" in over_wifi.clean


# ---------------------------------------------------------------- issue #31: geen curl

def without_curl(box):
    """Een PATH met alleen de stubs en de basisprogramma's, zonder curl. Slaat de test over als curl niet te weren is."""
    git_usr_bin = r"C:\Program Files\Git\usr\bin"
    path = f"{box.bin};{git_usr_bin}" if os.name == "nt" else f"{box.bin}:/usr/bin:/bin"
    (box.bin / "curl").unlink()
    probe = shutil.which("curl", path=path)
    if probe:
        pytest.skip(f"curl is hier niet te weren ({probe})")
    return path


def test_without_curl_the_internet_check_falls_back_to_python(box):
    healthy_server(box)
    result = preflight(box, PATH=without_curl(box))
    assert result.returncode == 0, result.clean
    assert "curl ontbreekt" in result.clean and result.clean.count("internet:") == 2 and "[FOUT]" not in result.clean


def test_without_curl_an_unreachable_site_is_still_an_error(box):
    healthy_server(box)
    result = preflight(box, PATH=without_curl(box), FAIL_HTTP="1")
    assert result.returncode == 1 and result.clean.count("niet bereikbaar") == 2


# ---------------------------------------------------------------- install.sh stopt bij een mislukte voorcontrole

def test_a_failed_preflight_blocks_the_installation_before_anything_changes(box):
    healthy_server(box)
    result = box.run("server", FAIL_HTTP="1", KIOSK_USER="kiosk")
    assert result.returncode != 0 and "voorcontrole vond fouten" in result.clean
    assert box.mutations() == []


def test_the_installation_continues_when_the_preflight_is_clean(box):
    healthy_server(box)
    result = box.run("server", KIOSK_USER="kiosk")
    assert result.returncode == 0, result.clean
    assert re.search(r"Geen fouten", result.clean) and "Gedaan: 10" in result.clean
