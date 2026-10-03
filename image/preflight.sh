#!/usr/bin/env bash
# Voorcontrole: kijkt zonder iets te wijzigen of deze Pi klaar is voor de installatie.
#
#   ./image/preflight.sh server     # voor de TEST-SERVER (Pi 5, met scherm)
#   ./image/preflight.sh client        # voor de TEST-CLIENT-SD van de TEST-CLIENT
#
# install.sh roept dit zelf eerst aan (overslaan kan met --skip-preflight).
# Eindigt met een foutcode als er iets is dat de installatie zou laten mislukken.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ROLE="${1:-}"
need_role "$ROLE"
printf 'Voorcontrole voor de %s\n\n' "$ROLE"

echo "Besturingssysteem en hardware"
codename="$(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-}")"
if [ "$codename" = trixie ]; then
  pass "Raspberry Pi OS Trixie"
else
  fail "besturingssysteem is '${codename:-onbekend}', Trixie is nodig (Bookworm heeft libgpiod 1.x)"
fi
if [ "$(uname -m)" = aarch64 ]; then
  pass "64-bit systeem"
else
  note "geen 64-bit systeem ($(uname -m)); 64-bit wordt aanbevolen"
fi

model="$({ tr -d '\0' </proc/device-tree/model; } 2>/dev/null)"  # accolades: ook de fout van het openen verdwijnt
case "$ROLE:$model" in
  server:*"Raspberry Pi 5"*) pass "model: $model" ;;
  server:*) note "de TEST-SERVER hoort een Pi 5 te zijn; gevonden: ${model:-onbekend} (niet getest)" ;;
  client:*"Raspberry Pi 4"*|client:*"Raspberry Pi 5"*) pass "model: $model" ;;
  client:*) note "dit is geen Pi 4 of 5: ${model:-onbekend}" ;;
esac

if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  pass "Python $(python3 -c 'import platform; print(platform.python_version())')"
else
  fail "Python 3.11 of nieuwer is nodig"
fi

free_kb="$(df -k --output=avail / 2>/dev/null | tail -n 1 | tr -d ' ')"
need_kb=$((2 * 1024 * 1024))
[ "$ROLE" = server ] && need_kb=$((3 * 1024 * 1024))  # de browser neemt ruimte
if [ -n "$free_kb" ] && [ "$free_kb" -ge "$need_kb" ]; then
  pass "vrije ruimte: $((free_kb / 1024)) MB"
else
  fail "te weinig vrije ruimte op de SD: ${free_kb:-?} kB (nodig: $need_kb kB)"
fi

echo
echo "Hulpprogramma's"
require_command raspi-config "pakket raspi-config; hoort bij Raspberry Pi OS"
require_command nmcli "NetworkManager; hoort bij Raspberry Pi OS Trixie"
require_command systemctl "systemd"
require_command curl "wordt bij de installatie bijgeplaatst" note

echo
echo "Netwerk"
if [ -e "/sys/class/net/$ETH_IFACE" ]; then
  pass "ethernetpoort $ETH_IFACE aanwezig"
else
  fail "ethernetpoort $ETH_IFACE niet gevonden; geef de juiste naam met ETH_IFACE=<naam>"
fi
for host in deb.debian.org archive.raspberrypi.com; do
  if curl -fsS -m 8 -o /dev/null "https://$host/" 2>/dev/null; then
    pass "internet: $host bereikbaar"
  else
    fail "$host niet bereikbaar (internet is nodig voor de pakketten); niet via $ETH_IFACE als dat de testkabel wordt"
  fi
done
if [ -n "${SSH_CONNECTION:-}" ]; then
  client_ip="$(echo "$SSH_CONNECTION" | awk '{print $1}')"
  via="$(ip route get "$client_ip" 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -n 1)"
  if [ "$via" = "$ETH_IFACE" ]; then
    note "je bent via $ETH_IFACE verbonden: het vaste testadres aan het eind van de installatie verbreekt deze sessie"
  else
    pass "SSH-sessie loopt via ${via:-?}, niet via $ETH_IFACE"
  fi
fi
if [ -d "$APP_DIR" ]; then
  note "$APP_DIR bestaat al: de installatie werkt de software bij"
fi

if [ "$ROLE" = server ]; then
  echo
  echo "TEST-SERVER: scherm, wifi en bluetooth"
  if command -v labwc >/dev/null 2>&1; then
    pass "bureaublad (labwc) aanwezig"
  else
    fail "labwc ontbreekt: gebruik Raspberry Pi OS met bureaublad (niet Lite)"
  fi
  hdmi=0
  for status in /sys/class/drm/card*-HDMI-A-*/status; do
    [ -r "$status" ] && [ "$(cat "$status")" = connected ] && hdmi=1
  done
  if [ "$hdmi" -eq 1 ]; then
    pass "scherm op HDMI herkend"
  else
    note "geen scherm op HDMI herkend (aansluiten, en de Pi daarna opnieuw opstarten)"
  fi
  kiosk_user="${KIOSK_USER:-${SUDO_USER:-}}"
  if [ -n "$kiosk_user" ] && id "$kiosk_user" >/dev/null 2>&1; then
    pass "gebruiker voor het scherm: $kiosk_user"
  else
    note "nog geen gebruiker voor het scherm bekend: start de installatie met sudo vanuit je gebruiker, of geef KIOSK_USER=<naam>"
  fi
  if ls /sys/class/net/*/wireless >/dev/null 2>&1 || ls /sys/class/net/*/phy80211 >/dev/null 2>&1; then
    pass "wifi-interface aanwezig (nodig voor het accesspoint)"
  else
    note "geen wifi-interface: de wifi-test wordt overgeslagen"
  fi
  if ls /sys/class/bluetooth/hci* >/dev/null 2>&1; then
    pass "bluetooth-controller aanwezig"
  else
    note "geen bluetooth-controller: de bluetooth-test wordt overgeslagen"
  fi
else
  echo
  echo "TEST-CLIENT-SD"
  note "de TEST-CLIENT hoeft geen scherm of bureaublad te hebben; Lite is genoeg"
fi

finish_checks
