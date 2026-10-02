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
