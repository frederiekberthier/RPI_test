"""Vaste afspraken en drempelwaarden voor de testopstelling.

De drempels zijn eerste schattingen en moeten geijkt worden met een bekend goede Pi.
"""

# --- directe kabel tussen testpi en DUT ---
TESTER_IP = "192.168.77.1"
DUT_IP = "192.168.77.2"
AGENT_PORT = 8765

# --- wired netwerk ---
IPERF_PORT = 5201
IPERF_SECONDS = 5
NET_MIN_MBIT_PASS = 800  # gigabit-TCP haalt op een gezonde Pi ca. 900+
NET_MIN_MBIT_WARN = 500  # tussen WARN en PASS: WARN; eronder: FAIL
PING_COUNT = 20
PING_MAX_RTT_MS = 2.0  # gemiddelde RTT boven dit: WARN (rechtstreekse kabel zit normaal onder 1 ms)
NET_ERRORS_WARN = 1  # aantal nieuwe rx/tx/crc-fouten tijdens de test
NET_ERRORS_FAIL = 100

# --- wifi: de testpi speelt accesspoint ---
# Wegwerp-netwerk op korte afstand; het wachtwoord is geen geheim (8 tot 63 tekens).
WIFI_SSID = "RPITEST"
WIFI_PASSWORD = "rpitest-wifi-2026"
WIFI_PROFILE = "rpitest-wifi"  # NetworkManager-profiel op de DUT
WIFI_AP_PROFILE = "rpitest-ap"  # NetworkManager-profiel van de hotspot op de testpi
# (label, nmcli-band, kanaal). Kanaal 36 is een niet-DFS-kanaal op 5 GHz.
WIFI_BANDS = (("2.4GHz", "bg", 6), ("5GHz", "a", 36))
WIFI_MIN_SIGNAL_DBM = -65  # zwakker op ca. 30 cm afstand: WARN (antenne/afscherming?)
WIFI_SCAN_TRIES = 3

# --- bluetooth ---
BT_SCAN_SECONDS = 10
