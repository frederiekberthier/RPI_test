#!/usr/bin/env bash
# Maakt van een kale Raspberry Pi OS (Trixie, MET bureaublad, 64-bit) de testpi:
# software, vast IP-adres, scherm met startknop (kiosk) en alles automatisch bij het opstarten.
#
#   sudo ./image/install-tester.sh                 # KIOSK_USER = de gebruiker die sudo gebruikte
#   sudo KIOSK_USER=pi WIFI_COUNTRY=BE ./image/install-tester.sh
#
# Opnieuw uitvoeren is veilig (werkt de software bij). Voor installatie of update is internet nodig:
# gebruik wifi of een USB-ethernetadapter, niet de poort die voor de testkabel bedoeld is.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

need_root
need_trixie

KIOSK_USER="${KIOSK_USER:-${SUDO_USER:-}}"
[ -n "$KIOSK_USER" ] && id "$KIOSK_USER" >/dev/null 2>&1 \
  || die "geen gebruiker voor het scherm: start met sudo vanuit je gebruiker, of geef KIOSK_USER=<naam>"
KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"

install_packages chromium
install_app

log "Naam van de Pi instellen"
hostnamectl set-hostname rpitest-tester || warn "hostname instellen mislukte"

free_gpio_pins
set_wifi_country

log "Automatisch inloggen op het bureaublad en schermbeveiliging uit"
raspi-config nonint do_boot_behaviour B4 || warn "automatisch inloggen instellen mislukte"
raspi-config nonint do_blanking 1 || warn "schermbeveiliging uitzetten mislukte"

log "Kioskbrowser starten bij het inloggen ($KIOSK_USER)"
# Een eigen autostart vervangt die van het bureaublad: geen taakbalk, enkel onze pagina.
install -d -o "$KIOSK_USER" -g "$KIOSK_USER" "$KIOSK_HOME/.config/labwc"
printf '%s\n' "$APP_DIR/kiosk.sh &" > "$KIOSK_HOME/.config/labwc/autostart"
chown "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.config/labwc/autostart"

log "Dienst installeren en starten"
install_unit rpitest-ui.service

# Als laatste: dit neemt de ethernetpoort over voor de testkabel (geen internet meer via eth0).
set_static_ip "$(config_value TESTER_IP)"

log "Klaar. Herstart de testpi (sudo reboot): het scherm start dan vanzelf."
warn "Vergeet niet: sluit de netwerkkabel van de testpi aan op de DUT, niet op het schoolnetwerk."
