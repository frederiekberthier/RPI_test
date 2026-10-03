#!/usr/bin/env bash
# Diagnose: verzamelt de ruwe uitvoer van alle tools waarop de tests steunen, in één tekstbestand.
# Wijzigt niets (alleen lezen en kort scannen). Bedoeld om bij een eerste run of een probleem naar
# de ontwikkelaar te sturen, zodat de parsers en aannames met echte uitvoer getoetst kunnen worden.
#
#   sudo ./image/diagnose.sh                 # schrijft naar /tmp/rpitest-diagnose-<naam>-<tijd>.txt
#   sudo ./image/diagnose.sh bestand.txt
#
# Het bestand bevat o.a. serienummer, MAC-adressen en namen van wifi-netwerken en bluetooth-apparaten
# in de buurt. Er staan geen wachtwoorden in.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

OUT="${1:-/tmp/rpitest-diagnose-$(hostname)-$(date +%Y%m%d-%H%M%S).txt}"
exec > >(tee "$OUT") 2>&1

section() { printf '\n==================== %s ====================\n' "$*"; }

# Voert een commando uit, toont het commando en de uitvoer (beperkt), en loopt nooit vast.
run() {
  printf '\n$ %s\n' "$*"
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "(niet geïnstalleerd: $1)"
    return 0
  fi
  timeout 25 "$@" 2>&1 | head -n 150
  return 0
}

# Idem voor een stukje shell met pijpen, bv. 'cat a | grep b'.
run_sh() {
  printf '\n$ %s\n' "$1"
  timeout 25 bash -c "$1" 2>&1 | head -n 150
  return 0
}

PY="$VENV/bin/python"
BT_SECONDS="$(config_value BT_SCAN_SECONDS 2>/dev/null || echo 10)"  # zelfde duur als de test
[ -x "$PY" ] || PY=python3

section "Algemeen"
run date
run uname -a
run_sh '. /etc/os-release; echo "$PRETTY_NAME ($VERSION_CODENAME)"'
run_sh 'tr -d "\0" </proc/device-tree/model; echo'
run_sh "grep -E '^(Model|Revision|Serial|Hardware)' /proc/cpuinfo"
run_sh "grep -E '^(MemTotal|MemAvailable)' /proc/meminfo"
run_sh 'cat /sys/devices/system/cpu/online /sys/devices/system/cpu/present'
run id
run_sh 'cat /etc/rpitest/ui.env 2>/dev/null || echo "(geen /etc/rpitest/ui.env)"'

section "Voeding en temperatuur (vcgencmd, sysfs)"
run vcgencmd get_throttled
run vcgencmd measure_temp
run vcgencmd pmic_read_adc
run_sh 'cat /sys/class/thermal/thermal_zone0/temp'
run_sh 'for f in scaling_cur_freq cpuinfo_max_freq scaling_governor; do echo -n "$f: "; cat /sys/devices/system/cpu/cpu0/cpufreq/$f; done'

section "GPIO"
run ls -l /dev/gpiochip0 /dev/gpiochip1 /dev/gpiochip2 /dev/gpiochip3 /dev/gpiochip4 /dev/gpiochip10
run gpiodetect
run "$PY" -m rpitest.agent --list-chips
run "$PY" -c "import gpiod; print('gpiod', getattr(gpiod, '__version__', '?'), 'api', getattr(gpiod, 'api_version', '?'), 'request_lines' in dir(gpiod))"
run_sh 'ls /dev/i2c-* /dev/spidev* 2>&1; grep -o "console=[^ ]*" /boot/firmware/cmdline.txt'

section "Netwerk"
run ip -br addr
run ip -4 route
run nmcli device status
run nmcli -t -f NAME,TYPE,DEVICE connection show
run_sh 'for i in /sys/class/net/*; do n=$(basename $i); [ "$n" = lo ] && continue; echo "--- $n"; for f in operstate carrier speed duplex address; do echo -n "$f="; cat $i/$f 2>&1; done; ls $i | grep -E "^(wireless|phy80211|device)$" | tr "\n" " "; echo; done'
run_sh 'cat /sys/class/net/eth0/statistics/rx_errors /sys/class/net/eth0/statistics/tx_errors /sys/class/net/eth0/statistics/rx_crc_errors 2>&1'
run ethtool eth0
run ping -c 3 -i 0.2 -q -W 1 127.0.0.1
run iperf3 --version

section "Wifi"
run iw dev
run iw reg get
run rfkill list
run_sh 'iw dev wlan0 link'
# precies de opdracht en velden die de test gebruikt
run nmcli -t -f SSID,SIGNAL,FREQ,BSSID dev wifi list --rescan yes

section "Bluetooth"
run bluetoothctl show
run_sh 'ls -l /sys/class/bluetooth/ 2>&1'
# precies de opdracht die de test gebruikt
run bluetoothctl --timeout "$BT_SECONDS" scan on

section "USB"
run lsusb -t
run lsblk -o NAME,SIZE,TRAN,MODEL,SERIAL
run_sh 'ls -l /sys/block/'
run_sh 'for d in /sys/bus/usb/devices/*; do n=$(basename $d); case $n in *:*|usb*) continue;; esac; echo "--- $n"; for f in idVendor idProduct manufacturer product serial speed bDeviceClass; do echo -n "$f="; cat $d/$f 2>/dev/null || echo; done; done'
run_sh "dmesg 2>&1 | grep -iE 'usb|xhci|over-?current' | tail -n 80"

section "Diensten van rpitest"
run systemctl status rpitest-ui.service rpitest-agent.service --no-pager
run_sh 'journalctl -u rpitest-ui -u rpitest-agent -n 80 --no-pager'
run_sh 'curl -fsS -m 5 http://127.0.0.1:8080/api/state | head -c 600; echo'
run_sh 'ls -l /var/lib/rpitest/reports 2>&1 | tail -n 10'
run_sh 'dpkg -l python3-libgpiod libgpiod2 libgpiod3 gpiod iperf3 iw bluez network-manager chromium libraspberrypi-bin 2>&1 | grep "^ii"'

printf '\nKlaar. Dit bestand staat in: %s\n' "$OUT"
