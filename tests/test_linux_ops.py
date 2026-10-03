import json

import pytest

from rpitest import config
from rpitest.system.linux import LinuxOps, ShellResult, list_ifaces, rfkill_state
from rpitest.system.ops import OpsError


class FakeShell:
    """Antwoordt op basis van het begin van de argumentenlijst; onthoudt alle aanroepen."""

    def __init__(self, answers):
        self.answers = answers  # lijst van (prefix-tuple, ShellResult)
        self.calls = []

    def run(self, argv, timeout=30):
        self.calls.append(argv)
        for prefix, result in self.answers:
            if tuple(argv[:len(prefix)]) == prefix:
                return result
        return ShellResult(127, "", f"{argv[0]}: niet gevonden")


def make_sys(tmp_path):
    net = tmp_path / "sys/class/net"
    for name, kind in (("lo", None), ("eth0", "device"), ("wlan0", "wireless"), ("docker0", None)):
        (net / name).mkdir(parents=True)
        if kind:
            (net / name / kind).mkdir()
    eth = net / "eth0"
    (eth / "statistics").mkdir()
    for fname, value in (("operstate", "up"), ("carrier", "1"), ("speed", "1000"), ("duplex", "full"),
                         ("address", "dc:a6:32:00:00:02")):
        (eth / fname).write_text(value + "\n")
    (eth / "statistics" / "rx_errors").write_text("7\n")
    rf = tmp_path / "sys/class/rfkill/rfkill0"
    rf.mkdir(parents=True)
    for fname, value in (("type", "wlan"), ("name", "phy0"), ("soft", "0"), ("hard", "1")):
        (rf / fname).write_text(value + "\n")
    return tmp_path


def test_list_ifaces_ignores_loopback_and_virtual(tmp_path):
    assert list_ifaces(make_sys(tmp_path)) == (["eth0"], ["wlan0"])
    assert list_ifaces(tmp_path / "bestaat-niet") == ([], [])


def test_rfkill_state(tmp_path):
    state = rfkill_state(make_sys(tmp_path))
    assert state == [{"type": "wlan", "name": "phy0", "soft_blocked": False, "hard_blocked": True}]


def test_net_iface_info_reads_sysfs(tmp_path):
    info = LinuxOps(FakeShell([]), make_sys(tmp_path)).net_iface_info()
    assert info["name"] == "eth0" and info["speed_mbit"] == 1000 and info["carrier"] == 1
    assert info["stats"]["rx_errors"] == 7 and info["stats"]["tx_errors"] == 0


def test_ping_builds_safe_argv(tmp_path):
    out = "5 packets transmitted, 5 received, 0% packet loss, time 800ms\nrtt min/avg/max/mdev = 0.1/0.2/0.3/0.0 ms\n"
    shell = FakeShell([(("ping",), ShellResult(0, out))])
    LinuxOps(shell, tmp_path).ping("192.168.77.2", 5)
    assert shell.calls[0] == ["ping", "-c", "5", "-i", "0.2", "-q", "-W", "1", "192.168.77.2"]


def test_missing_tool_gives_clear_error(tmp_path):
    with pytest.raises(OpsError, match="niet gevonden"):
        LinuxOps(FakeShell([]), tmp_path).iperf3_client("192.168.77.2", 5, reverse=False)


def test_iperf3_client_reverse_flag(tmp_path):
    out = json.dumps({"end": {"sum_received": {"bits_per_second": 9e8}}})
    shell = FakeShell([(("iperf3",), ShellResult(0, out))])
    result = LinuxOps(shell, tmp_path).iperf3_client("192.168.77.2", 5, reverse=True)
    assert result["mbit_per_s"] == 900.0
    assert shell.calls[0][-1] == "-R" and "-J" in shell.calls[0]


def test_wifi_connect_passes_credentials_as_separate_arguments(tmp_path):
    shell = FakeShell([(("nmcli", "connection"), ShellResult(0)),
                       (("nmcli", "-w"), ShellResult(0)),
                       (("ip",), ShellResult(0, "3: wlan0    inet 10.42.0.57/24 scope global\n"))])
    result = LinuxOps(shell, make_sys(tmp_path)).wifi_connect("RPITEST", "geheim wachtwoord; rm -rf /")
    assert result == {"ip": "10.42.0.57"}
    connect = next(c for c in shell.calls if c[:2] == ["nmcli", "-w"])
    assert "geheim wachtwoord; rm -rf /" in connect  # één argument, geen shell die het interpreteert
    assert connect[connect.index("ifname") + 1] == "wlan0"


def test_wifi_connect_failure_is_reported(tmp_path):
    shell = FakeShell([(("nmcli", "connection"), ShellResult(0)),
                       (("nmcli", "-w"), ShellResult(4, "", "Error: No network with SSID 'X' found."))])
    with pytest.raises(OpsError, match="No network"):
        LinuxOps(shell, make_sys(tmp_path)).wifi_connect("X", "wachtwoord1")


def test_hotspot_command(tmp_path):
    shell = FakeShell([(("nmcli",), ShellResult(0)), (("ip",), ShellResult(0, "inet 10.42.0.1/24 scope global"))])
    ap = LinuxOps(shell, make_sys(tmp_path)).wifi_hotspot_start("RPITEST", "wachtwoord1", "a", 36)
    assert ap == {"ip": "10.42.0.1"}
    cmd = next(c for c in shell.calls if "hotspot" in c)
    assert cmd[cmd.index("band") + 1] == "a" and cmd[cmd.index("channel") + 1] == "36"
    assert cmd[cmd.index("con-name") + 1] == config.WIFI_AP_PROFILE


def test_bt_info_powers_on_adapter(tmp_path):
    responses = iter(["Controller DC:A6:32:00:00:01 (public)\n\tPowered: no\n",
                      "Controller DC:A6:32:00:00:01 (public)\n\tPowered: yes\n"])

    class Shell(FakeShell):
        def run(self, argv, timeout=30):
            self.calls.append(argv)
            return ShellResult(0, next(responses) if argv[1:] == ["show"] else "")

    shell = Shell([])
    info = LinuxOps(shell, tmp_path).bt_info()
    assert info["powered"] is True and ["bluetoothctl", "power", "on"] in shell.calls


def test_bt_scan_forgets_target_first(tmp_path):
    shell = FakeShell([(("bluetoothctl", "remove"), ShellResult(0)),
                       (("bluetoothctl", "--timeout"), ShellResult(0, "[NEW] Device DC:A6:32:00:00:01 pi\n"))])
    found = LinuxOps(shell, tmp_path).bt_scan(5, "DC:A6:32:00:00:01")
    assert shell.calls[0] == ["bluetoothctl", "remove", "DC:A6:32:00:00:01"]
    assert found[0]["address"] == "DC:A6:32:00:00:01"


# ---------------------------------------------------------------- issue #7: kies de juiste interface

def add_iface(root, name, kind, speed="100", mac="aa:bb:cc:00:00:99"):
    path = root / "sys/class/net" / name
    (path / kind).mkdir(parents=True)
    (path / "statistics").mkdir()
    for fname, value in (("operstate", "up"), ("carrier", "1"), ("speed", speed), ("duplex", "full"), ("address", mac)):
        (path / fname).write_text(value + "\n")


def test_onboard_eth0_is_preferred_over_a_usb_ethernet_adapter(tmp_path):
    root = make_sys(tmp_path)
    add_iface(root, "enxa0cec8123456", "device", speed="100")  # sorteert vóór 'eth0'
    info = LinuxOps(FakeShell([]), root).net_iface_info()
    assert info["name"] == "eth0" and info["speed_mbit"] == 1000


def test_the_interface_carrying_the_test_address_is_used_when_eth0_does_not_exist(tmp_path):
    root = make_sys(tmp_path)
    import shutil
    shutil.rmtree(root / "sys/class/net/eth0")
    add_iface(root, "enp1s0", "device")
    add_iface(root, "enxa0cec8123456", "device")
    ip_out = ("2: enp1s0    inet 10.0.0.5/24 brd 10.0.0.255 scope global\n"
              "3: enxa0cec8123456    inet 192.168.77.1/24 scope global\n")
    ops = LinuxOps(FakeShell([(("ip",), ShellResult(0, ip_out))]), root)
    assert ops.net_iface_info()["name"] == "enxa0cec8123456"


def test_an_explicit_interface_name_wins(tmp_path):
    root = make_sys(tmp_path)
    add_iface(root, "enxa0cec8123456", "device")
    assert LinuxOps(FakeShell([]), root, eth_iface="enxa0cec8123456").net_iface_info()["name"] == "enxa0cec8123456"


def test_onboard_wlan0_is_preferred_over_a_usb_wifi_adapter(tmp_path):
    root = make_sys(tmp_path)
    add_iface(root, "wlaa-usb", "wireless")  # sorteert vóór 'wlan0'
    shell = FakeShell([(("iw",), ShellResult(0, "Not connected.\n")), (("ip",), ShellResult(0, ""))])
    LinuxOps(shell, root).wifi_link()
    assert shell.calls[0] == ["iw", "dev", "wlan0", "link"]


def test_ip_address_parser():
    from rpitest.system.parsers import parse_ip_addresses
    text = "2: eth0    inet 192.168.77.2/24 brd 192.168.77.255 scope global eth0\n3: wlan0    inet 10.42.0.5/24 scope global\n"
    assert parse_ip_addresses(text) == {"eth0": "192.168.77.2", "wlan0": "10.42.0.5"}


# ---------------------------------------------------------------- issue #11: de fout van een falende tool blijft zichtbaar

def test_a_failing_ping_reports_its_error_instead_of_unreadable_output(tmp_path):
    shell = FakeShell([(("ping",), ShellResult(2, "", "ping: connect: Network is unreachable"))])
    with pytest.raises(OpsError, match="Network is unreachable"):
        LinuxOps(shell, tmp_path).ping("192.168.77.2", 5)


def test_a_ping_with_total_loss_is_still_a_result_not_an_error(tmp_path):
    out = "5 packets transmitted, 0 received, 100% packet loss, time 800ms\n"
    result = LinuxOps(FakeShell([(("ping",), ShellResult(1, out))]), tmp_path).ping("192.168.77.2", 5)
    assert result["loss_pct"] == 100.0


def test_a_failing_iperf3_reports_its_error(tmp_path):
    shell = FakeShell([(("iperf3",), ShellResult(1, "", "iperf3: error - unable to connect to server"))])
    with pytest.raises(OpsError, match="unable to connect"):
        LinuxOps(shell, tmp_path).iperf3_client("192.168.77.2", 5, reverse=False)


def test_iw_link_on_a_missing_device_is_an_error_but_not_connected_is_a_result(tmp_path):
    make_sys(tmp_path)
    shell = FakeShell([(("iw",), ShellResult(1, "", "command failed: No such device (-19)")), (("ip",), ShellResult(0))])
    with pytest.raises(OpsError, match="No such device"):
        LinuxOps(shell, tmp_path).wifi_link()
    shell = FakeShell([(("iw",), ShellResult(0, "Not connected.\n")), (("ip",), ShellResult(0))])
    assert LinuxOps(shell, tmp_path).wifi_link()["connected"] is False
    shell = FakeShell([(("iw",), ShellResult(1, "Not connected.\n")), (("ip",), ShellResult(0))])
    assert LinuxOps(shell, tmp_path).wifi_link()["connected"] is False


def test_a_bluetooth_scan_that_never_started_is_an_error_not_an_empty_list(tmp_path):
    shell = FakeShell([(("bluetoothctl",), ShellResult(1, "", "No default controller available"))])
    with pytest.raises(OpsError, match="No default controller"):
        LinuxOps(shell, tmp_path).bt_scan(5)
    started = "Discovery started\n[NEW] Device DC:A6:32:00:00:01 pi\n"  # een afsluitcode bij de time-out is geen fout
    found = LinuxOps(FakeShell([(("bluetoothctl",), ShellResult(1, started))]), tmp_path).bt_scan(5)
    assert [d["address"] for d in found] == ["DC:A6:32:00:00:01"]
    assert LinuxOps(FakeShell([(("bluetoothctl",), ShellResult(0, "Discovery started\n"))]), tmp_path).bt_scan(5) == []


# ---------------------------------------------------------------- issue #12: vaste taal en geen invoer

def test_shell_runs_tools_in_the_c_locale_without_stdin(monkeypatch):
    import sys
    from rpitest.system.linux import Shell
    monkeypatch.setenv("LC_ALL", "nl_BE.UTF-8")
    monkeypatch.setenv("LANG", "nl_BE.UTF-8")
    code = "import os, sys; print(os.environ.get('LC_ALL'), os.environ.get('LANG'), repr(sys.stdin.read()))"
    result = Shell().run([sys.executable, "-c", code])
    assert result.stdout.split() == ["C", "C", "''"], result


# ---------------------------------------------------------------- issue #13: vreemde bytes in sysfs

def test_usb_scan_survives_undecodable_descriptor_strings(tmp_path, monkeypatch):
    from pathlib import Path
    original = Path.read_text

    def strict_utf8(self, encoding=None, errors=None):  # zoals de Pi: standaard strikt UTF-8 (op Windows is dat cp1252)
        return original(self, encoding=encoding or "utf-8", errors=errors)
    monkeypatch.setattr(Path, "read_text", strict_utf8)
    device = tmp_path / "sys/bus/usb/devices/1-1"
    device.mkdir(parents=True)
    (device / "idVendor").write_text("0781\n")
    (device / "idProduct").write_text("5567\n")
    (device / "serial").write_bytes(b"AB\xed\xa0\x80CD\n")
    (device / "product").write_bytes(b"Cruzer \xff Blade\n")
    devices = LinuxOps(FakeShell([]), tmp_path).usb_scan()
    assert devices[0]["vid"] == "0781" and devices[0]["serial"].startswith("AB") and "Cruzer" in devices[0]["product"]
