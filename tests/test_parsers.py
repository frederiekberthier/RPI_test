"""Voorbeelduitvoer is uit het geheugen opgebouwd, niet van echte Pi's gekopieerd.
Bevestig op de eerste echte run dat de formaten kloppen en vervang dan deze voorbeelden
door echte uitvoer."""

import json

import pytest

from rpitest.system import parsers
from rpitest.system.ops import OpsError

PING = """PING 192.168.77.2 (192.168.77.2) 56(84) bytes of data.

--- 192.168.77.2 ping statistics ---
20 packets transmitted, 19 received, 5% packet loss, time 3815ms
rtt min/avg/max/mdev = 0.231/0.289/0.512/0.061 ms
"""


def test_parse_ping():
    r = parsers.parse_ping(PING)
    assert (r["sent"], r["received"], r["loss_pct"]) == (20, 19, 5.0)
    assert r["rtt_avg_ms"] == 0.289 and r["rtt_max_ms"] == 0.512


def test_parse_ping_total_loss_has_no_rtt():
    r = parsers.parse_ping("--- x ping statistics ---\n5 packets transmitted, 0 received, 100% packet loss, time 4ms\n")
    assert r["loss_pct"] == 100.0 and r["rtt_avg_ms"] is None


def test_parse_ping_garbage():
    with pytest.raises(OpsError):
        parsers.parse_ping("ping: unknown host")


def test_parse_iperf3():
    text = json.dumps({"end": {"sum_sent": {"retransmits": 3, "bits_per_second": 9.5e8},
                               "sum_received": {"bits_per_second": 9.41e8}}})
    assert parsers.parse_iperf3(text) == {"mbit_per_s": 941.0, "retransmits": 3}


def test_parse_iperf3_error_and_garbage():
    with pytest.raises(OpsError, match="unable to connect"):
        parsers.parse_iperf3(json.dumps({"error": "unable to connect to server"}))
    with pytest.raises(OpsError):
        parsers.parse_iperf3("not json")


def test_split_terse_handles_escaped_colons():
    assert parsers.split_terse(r"RPITEST:80:5180 MHz:AA\:BB\:CC\:DD\:EE\:FF") == [
        "RPITEST", "80", "5180 MHz", "AA:BB:CC:DD:EE:FF"]


def test_parse_wifi_scan_skips_hidden_and_broken_lines():
    text = "RPITEST:80:5180 MHz:AA\\:BB\\:CC\\:DD\\:EE\\:FF\n:40:2412 MHz:11\\:22\\:33\\:44\\:55\\:66\nkapot\n"
    nets = parsers.parse_wifi_scan(text)
    assert nets == [{"ssid": "RPITEST", "signal_pct": 80, "freq_mhz": 5180, "bssid": "AA:BB:CC:DD:EE:FF"}]


def test_parse_iw_link():
    text = """Connected to aa:bb:cc:dd:ee:ff (on wlan0)
\tSSID: RPITEST
\tfreq: 5180
\tsignal: -42 dBm
\trx bitrate: 433.3 MBit/s VHT-MCS 4 80MHz
\ttx bitrate: 390.0 MBit/s VHT-MCS 4 80MHz
"""
    assert parsers.parse_iw_link(text) == {"connected": True, "ssid": "RPITEST", "freq_mhz": 5180,
                                           "signal_dbm": -42.0, "tx_mbit": 390.0, "rx_mbit": 433.3}
    assert parsers.parse_iw_link("Not connected.\n") == {"connected": False}


def test_parse_ip_addr():
    assert parsers.parse_ip_addr("3: wlan0    inet 10.42.0.57/24 brd 10.42.0.255 scope global\n") == "10.42.0.57"
    assert parsers.parse_ip_addr("") is None


def test_parse_bluetoothctl_show():
    text = "Controller DC:A6:32:12:34:56 (public)\n\tName: raspberrypi\n\tPowered: yes\n\tDiscoverable: no\n"
    assert parsers.parse_bluetoothctl_show(text) == {"present": True, "address": "DC:A6:32:12:34:56", "powered": True}
    assert parsers.parse_bluetoothctl_show("No default controller available\n")["present"] is False


def test_parse_bluetooth_scan_with_ansi_and_both_rssi_formats():
    text = (
        "Discovery started\n"
        "\x1b[0;92m[NEW]\x1b[0m Device DC:A6:32:00:00:01 raspberrypi\n"
        "[CHG] Device DC:A6:32:00:00:01 RSSI: 0xffffffc4 (-60)\n"
        "[NEW] Device 11:22:33:44:55:66 11-22-33-44-55-66\n"
        "[CHG] Device 11:22:33:44:55:66 RSSI: -71\n"
        "[CHG] Device 77:88:99:AA:BB:CC Connected: no\n"  # geen NEW of RSSI: niet gezien
        "[DEL] Device 11:22:33:44:55:66 x\n"
    )
    found = {d["address"]: d for d in parsers.parse_bluetooth_scan(text)}
    assert set(found) == {"DC:A6:32:00:00:01", "11:22:33:44:55:66"}
    assert found["DC:A6:32:00:00:01"]["rssi"] == -60 and found["DC:A6:32:00:00:01"]["name"] == "raspberrypi"
    assert found["11:22:33:44:55:66"]["rssi"] == -71
