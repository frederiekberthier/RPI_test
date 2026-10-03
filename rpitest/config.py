"""Vaste afspraken en drempelwaarden voor de testopstelling.

De drempels zijn eerste schattingen en moeten geijkt worden met een bekend goede Pi.
"""

# --- directe kabel tussen TEST-SERVER en TEST-CLIENT ---
SERVER_IP = "192.168.77.1"
CLIENT_IP = "192.168.77.2"
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

# --- wifi: de TEST-SERVER speelt accesspoint ---
# Wegwerp-netwerk op korte afstand; het wachtwoord is geen geheim (8 tot 63 tekens).
WIFI_SSID = "RPITEST"
WIFI_PASSWORD = "rpitest-wifi-2026"
WIFI_PROFILE = "rpitest-wifi"  # NetworkManager-profiel op de TEST-CLIENT
WIFI_AP_PROFILE = "rpitest-ap"  # NetworkManager-profiel van de hotspot op de TEST-SERVER
# (label, nmcli-band, kanaal). Kanaal 36 is een niet-DFS-kanaal op 5 GHz.
WIFI_BANDS = (("2.4GHz", "bg", 6), ("5GHz", "a", 36))
WIFI_MIN_SIGNAL_DBM = -65  # zwakker op ca. 30 cm afstand: WARN (antenne/afscherming?)
WIFI_SCAN_TRIES = 3

# --- bluetooth ---
BT_SCAN_SECONDS = 10

# --- usb: vier voorbereide teststicks in een vaste fixture ---
# Elke stick heeft een label in sector 0 (zie `python -m rpitest.usbtools prepare`). Het label geeft
# aan welke stick (en dus welke poort van de fixture) bedoeld wordt. SLOT1/2 horen in de blauwe
# USB3-poorten te zitten met USB3-sticks, SLOT3/4 in de zwarte USB2-poorten.
USB_TEST_MB = 32
USB_SLOTS = (
    {"label": "SLOT1", "name": "USB3 poort 1", "min_speed_mbit": 5000, "min_read_mb_s": 60},
    {"label": "SLOT2", "name": "USB3 poort 2", "min_speed_mbit": 5000, "min_read_mb_s": 60},
    {"label": "SLOT3", "name": "USB2 poort 1", "min_speed_mbit": 480, "min_read_mb_s": 15},
    {"label": "SLOT4", "name": "USB2 poort 2", "min_speed_mbit": 480, "min_read_mb_s": 15},
)

# --- voeding, temperatuur en belasting ---
STRESS_SECONDS = 60
STRESS_POLL_S = 2
STRESS_RAM_MB = 256  # wordt begrensd tot de helft van het beschikbare geheugen
EXPECTED_CORES = 4  # Pi 4 en Pi 5
TEMP_IDLE_WARN_C = 60  # in rust (na het opstarten) al zo warm: WARN
TEMP_WARN_C = 80  # hier begint de Pi te throttlen: WARN
TEMP_FAIL_C = 85
MIN_5V_VOLT = 4.75  # gemeten ingangsspanning (Pi 5) onder belasting: WARN
THROTTLE_FREQ_RATIO = 0.9  # klokfrequentie onder 90% van het maximum tijdens de belasting: WARN
SLOW_CORE_RATIO = 0.5  # een kern die minder dan de helft van de mediaan haalt: WARN
