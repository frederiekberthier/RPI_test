#!/usr/bin/env bash
# Gedeelde functies voor install-tester.sh en install-dut.sh. Wordt gesourced, niet los gestart.

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

IMAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$IMAGE_DIR/.." && pwd)"
APP_DIR=/opt/rpitest
VENV="$APP_DIR/venv"
DATA_DIR=/var/lib/rpitest
ETH_IFACE="${ETH_IFACE:-eth0}"
WIFI_COUNTRY="${WIFI_COUNTRY:-BE}"
NM_PROFILE=rpitest

# --- controles (preflight.sh en verify.sh): tellen fouten en waarschuwingen, wijzigen niets ---
CHECKS_FAILED=0
CHECKS_WARNED=0
pass() { printf '  \033[1;32m[ok]\033[0m      %s\n' "$*"; }
fail() { printf '  \033[1;31m[FOUT]\033[0m    %s\n' "$*"; CHECKS_FAILED=$((CHECKS_FAILED + 1)); }
note() { printf '  \033[1;33m[let op]\033[0m  %s\n' "$*"; CHECKS_WARNED=$((CHECKS_WARNED + 1)); }

finish_checks() {
  echo
  if [ "$CHECKS_FAILED" -gt 0 ]; then
    printf '%s fout(en), %s waarschuwing(en): los de fouten eerst op.\n' "$CHECKS_FAILED" "$CHECKS_WARNED"
    return 1
  fi
  printf 'Geen fouten, %s waarschuwing(en).\n' "$CHECKS_WARNED"
}

need_role() {
  case "${1:-}" in
    tester|dut) ;;
    *) die "gebruik: $0 tester|dut" ;;
  esac
}

# Is dit commando beschikbaar? Geeft [ok] of een melding terug; $3 = fail of note.
require_command() {
  local cmd="$1" hint="$2" severity="${3:-fail}"
  if command -v "$cmd" >/dev/null 2>&1; then
    pass "$cmd aanwezig"
  else
    "$severity" "$cmd ontbreekt ($hint)"
  fi
}

need_root() {
  [ "$(id -u)" -eq 0 ] || die "start dit script met sudo"
}

need_trixie() {
  # libgpiod 2.x zit pas in Debian 13 (Trixie); Bookworm levert 1.x met een andere API.
  local codename
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
  if [ "$codename" != "trixie" ]; then
    die "dit werkt alleen op Raspberry Pi OS Trixie (gevonden: ${codename:-onbekend}); Bookworm heeft libgpiod 1.x"
  fi
}

# Waarden uit de Python-configuratie halen, zodat IP-adressen maar op een plaats staan (rpitest/config.py).
config_value() {
  (cd "$REPO_DIR" && python3 -c "from rpitest import config; print(config.$1)")
}

install_packages() {
  log "Pakketten installeren"
  apt-get update
  # libraspberrypi-bin levert vcgencmd (onderspanning, temperatuur); dnsmasq-base is nodig voor de wifi-hotspot.
  apt-get install -y python3-venv python3-libgpiod iperf3 iw rfkill bluez network-manager \
    dnsmasq-base curl "$@"
  apt-get install -y libraspberrypi-bin || warn "libraspberrypi-bin niet installeerbaar: vcgencmd ontbreekt"
}

install_app() {
  log "Software installeren in $VENV"
  mkdir -p "$APP_DIR" "$DATA_DIR"
  # --system-site-packages: de module 'gpiod' komt uit het Debian-pakket python3-libgpiod
  python3 -m venv --system-site-packages "$VENV"
  "$VENV/bin/pip" install --upgrade "$REPO_DIR"
  install -m 0755 "$IMAGE_DIR/kiosk.sh" "$APP_DIR/kiosk.sh"
}

install_unit() {
  local unit="$1"
  install -m 0644 "$IMAGE_DIR/systemd/$unit" "/etc/systemd/system/$unit"
  systemctl daemon-reload
  systemctl enable "$unit"
  systemctl restart "$unit" || warn "$unit startte niet meteen; zie: journalctl -u $unit"
}

# Vast IP-adres op de rechtstreekse kabel (geen gateway: dit is alleen de testkabel).
set_static_ip() {
  local address="$1"
  log "Vast IP-adres $address/24 op $ETH_IFACE"
  # zonder grep -q: dat sluit de pijp vroeg en geeft met 'pipefail' een vals negatief resultaat
  if nmcli -t -f NAME connection show | grep -x "$NM_PROFILE" >/dev/null; then
    nmcli connection delete "$NM_PROFILE" >/dev/null
  fi
  nmcli connection add type ethernet ifname "$ETH_IFACE" con-name "$NM_PROFILE" \
    ipv4.method manual ipv4.addresses "$address/24" ipv6.method disabled \
    connection.autoconnect yes >/dev/null
  nmcli connection up "$NM_PROFILE" 2>/dev/null || warn "profiel nog niet actief (geen kabel aangesloten?); start vanzelf bij link"
}

# I2C, SPI en de seriële poort houden GPIO-pinnen bezet; die moeten vrij zijn voor de test.
free_gpio_pins() {
  log "I2C, SPI en seriële console uitschakelen"
  for step in "do_i2c 1" "do_spi 1" "do_serial_hw 1" "do_serial_cons 1"; do
    raspi-config nonint $step || warn "raspi-config nonint $step mislukte"
  done
}

set_wifi_country() {
  log "Wifi-land $WIFI_COUNTRY instellen (nodig voor het 5 GHz-accesspoint)"
  raspi-config nonint do_wifi_country "$WIFI_COUNTRY" || warn "wifi-land instellen mislukte"
  rfkill unblock wifi || true
}
