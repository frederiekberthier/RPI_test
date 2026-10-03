#!/usr/bin/env bash
# Maakt van een kale Raspberry Pi OS (Trixie, Lite is genoeg) de tester-SD voor de te testen Pi:
# de agent start vanzelf bij het opstarten en luistert op het vaste testadres.
#
#   sudo ./image/install-dut.sh
#   sudo ./image/install-dut.sh --readonly     # daarna: het bestandssysteem wordt alleen-lezen
#
# --readonly zet als laatste stap een overlay aan, zodat een Pi die zonder af te sluiten
# uitgezet wordt de SD niet kan beschadigen. Wijzigingen (ook updates) gaan dan na een herstart verloren;
# schakel het eerst uit (raspi-config > Performance Options > Overlay File System) om bij te werken.
# Voor installatie is internet nodig: sluit de Pi voor dit script aan op het gewone netwerk.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

READONLY=0
[ "${1:-}" = "--readonly" ] && READONLY=1

need_root
need_trixie

install_packages
install_app

log "Naam van de Pi instellen"
hostnamectl set-hostname rpitest-dut || warn "hostname instellen mislukte"

free_gpio_pins
set_wifi_country

log "Agent installeren en starten"
install_unit rpitest-agent.service

# Als laatste: dit neemt de ethernetpoort over voor de testkabel (geen internet meer via eth0).
set_static_ip "$(config_value DUT_IP)"

if [ "$READONLY" -eq 1 ]; then
  log "Alleen-lezen overlay inschakelen (actief na herstart)"
  raspi-config nonint enable_overlayfs || warn "overlay inschakelen mislukte"
  raspi-config nonint enable_bootro || warn "alleen-lezen bootpartitie inschakelen mislukte"
fi

log "Klaar. Herstart de Pi (sudo reboot); de agent start vanzelf op $(config_value DUT_IP):$(config_value AGENT_PORT)."
