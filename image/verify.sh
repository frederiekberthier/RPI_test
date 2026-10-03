#!/usr/bin/env bash
# Natest: controleert na de installatie (en na de herstart) of alles draait zoals bedoeld.
# Wijzigt niets.
#
#   sudo ./image/verify.sh server
#   sudo ./image/verify.sh client
#
# Draai dit eerst zonder de TEST-CLIENT aangesloten en daarna nog eens met alles aangesloten.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ROLE="${1:-}"
need_role "$ROLE"
[ "$(id -u)" -eq 0 ] || die "start dit script met sudo (dmesg en vcgencmd vragen dat)"
printf 'Natest voor de %s\n\n' "$ROLE"

PY="$VENV/bin/python"
SERVER_IP="$(config_value SERVER_IP)"
CLIENT_IP="$(config_value CLIENT_IP)"
AGENT_PORT="$(config_value AGENT_PORT)"
UI_PORT=8080

# Vraagt de agent op de TEST-CLIENT of hij antwoordt (zelfde aanroep die de TEST-SERVER gebruikt).
agent_pong() {
  curl -fsS -m 4 -X POST "http://$CLIENT_IP:$AGENT_PORT/rpc" -H 'Content-Type: application/json' \
    -d '{"method":"ping","params":{}}' 2>/dev/null | grep -q pong
}

check_unit() {
  if systemctl is-enabled --quiet "$1" 2>/dev/null; then
    pass "$1 start bij het opstarten"
  else
    fail "$1 staat niet aan voor het opstarten"
  fi
  if systemctl is-active --quiet "$1" 2>/dev/null; then
    pass "$1 draait"
  else
    fail "$1 draait niet; zie: journalctl -u $1 -n 50"
  fi
}

echo "Software"
if "$PY" -I -c "import rpitest, gpiod" 2>/dev/null; then
  pass "rpitest en gpiod importeren in $VENV"
else
  fail "rpitest of gpiod niet te importeren in $VENV (installatie onvolledig, of libgpiod 1.x?)"
fi
chips="$("$PY" -I -m rpitest.agent --list-chips 2>&1)"
if echo "$chips" | grep -Eq 'label=pinctrl-(rp1|bcm2711|bcm2835)'; then
  pass "GPIO-chip van de header gevonden: $(echo "$chips" | grep -E 'label=pinctrl-' | head -n 1)"
else
  fail "GPIO-chip van de header niet gevonden; uitvoer van --list-chips: $chips"
fi

echo
echo "Diensten"
if [ "$ROLE" = server ]; then
  check_unit rpitest-ui.service
else
  check_unit rpitest-agent.service
fi

echo
echo "Netwerk"
if nmcli -t -f NAME connection show | grep -x "$NM_PROFILE" >/dev/null; then
  pass "NetworkManager-profiel '$NM_PROFILE' aanwezig"
else
  fail "NetworkManager-profiel '$NM_PROFILE' ontbreekt"
fi
want_ip="$SERVER_IP"
[ "$ROLE" = client ] && want_ip="$CLIENT_IP"
if ip -4 addr show dev "$ETH_IFACE" 2>/dev/null | grep -q "inet $want_ip/"; then
  pass "$ETH_IFACE heeft $want_ip"
else
  note "$ETH_IFACE heeft $want_ip niet: normaal als er geen kabel in zit (NetworkManager wacht op link)"
fi

echo
echo "Pinnen vrij voor de test (I2C, SPI en seriële console uit)"
[ -e "$SYS_ROOT/dev/i2c-1" ] && fail "I2C staat aan (/dev/i2c-1): houdt GPIO2 en 3 bezet" || pass "I2C uit"
if ls "$SYS_ROOT"/dev/spidev* >/dev/null 2>&1; then fail "SPI staat aan: houdt GPIO7 tot 11 bezet"; else pass "SPI uit"; fi
if grep -Eq 'console=(serial0|ttyAMA0|ttyS0)' "$SYS_ROOT/boot/firmware/cmdline.txt" 2>/dev/null; then
  fail "seriële console staat aan: houdt GPIO14 en 15 bezet"
else
  pass "seriële console uit"
fi

echo
echo "Hulpprogramma's voor de tests"
require_command iperf3 "pakket iperf3"
require_command iw "pakket iw"
require_command bluetoothctl "pakket bluez"
require_command vcgencmd "pakket libraspberrypi-bin; zonder dit geen onderspanningsmeting" note

if [ "$ROLE" = server ]; then
  echo
  echo "Scherm"
  state="$(curl -fsS -m 5 "http://127.0.0.1:$UI_PORT/api/state" 2>/dev/null)"
  if echo "$state" | "$PY" -c 'import sys, json; json.load(sys.stdin)["phase"]' 2>/dev/null; then
    pass "de webpagina antwoordt op 127.0.0.1:$UI_PORT"
  else
    fail "de webpagina antwoordt niet op 127.0.0.1:$UI_PORT"
  fi
  [ -d "$DATA_DIR/reports" ] && pass "rapportmap $DATA_DIR/reports bestaat" \
    || note "rapportmap $DATA_DIR/reports bestaat nog niet (wordt bij de eerste run gemaakt)"
  kiosk_user="${KIOSK_USER:-${SUDO_USER:-}}"
  if [ -n "$kiosk_user" ]; then
    home="${KIOSK_HOME:-$(getent passwd "$kiosk_user" | cut -d: -f6)}"
    if grep -q "$APP_DIR/kiosk.sh" "$home/.config/labwc/autostart" 2>/dev/null; then
      pass "autostart van de kioskbrowser staat in $home/.config/labwc/autostart"
    else
      fail "autostart van de kioskbrowser ontbreekt in $home/.config/labwc/autostart"
    fi
  else
    note "geen gebruiker bekend: autostart niet gecontroleerd (start met sudo vanuit je gebruiker, of geef KIOSK_USER)"
  fi
  if pgrep -f chromium >/dev/null 2>&1; then
    pass "de kioskbrowser draait"
  else
    note "de kioskbrowser draait niet: normaal tot de eerste herstart en automatische login"
  fi
  echo
  echo "Verbinding met de TEST-CLIENT"
  if agent_pong; then
    pass "de agent op de TEST-CLIENT ($CLIENT_IP:$AGENT_PORT) antwoordt"
  else
    note "de agent op de TEST-CLIENT antwoordt niet: nog niet aangesloten of opgestart?"
  fi
else
  echo
  echo "Agent"
  if agent_pong; then
    pass "de agent antwoordt op $CLIENT_IP:$AGENT_PORT"
  else
    note "de agent antwoordt niet op $CLIENT_IP:$AGENT_PORT (geen kabel? het adres wordt pas actief bij link)"
  fi
  if [ "$(findmnt -n -o FSTYPE / 2>/dev/null)" = overlay ]; then
    note "alleen-lezen overlay is actief: wijzigingen gaan bij een herstart verloren (zo hoort het voor de klaar-SD)"
  fi
fi

finish_checks
