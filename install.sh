#!/usr/bin/env bash
# Eén script om een Raspberry Pi klaar te maken als TEST-SERVER of als TEST-CLIENT-SD voor de TEST-CLIENT.
# Het doet alles: voorcontrole, pakketten (apt), software, hostnaam, vrije GPIO-pinnen, wifi-land, scherm
# met kiosk (TEST-SERVER), systemd-dienst en het vaste IP-adres.
#
#   sudo ./install.sh server            # de TEST-SERVER (Pi 5, met scherm)
#   sudo ./install.sh client               # de TEST-CLIENT-SD voor de TEST-CLIENT
#
# Opties:
#   --check           toon alleen wat al geïnstalleerd is en wat ontbreekt; wijzigt niets
#   --force           pas alles opnieuw toe, ook wat al aanwezig lijkt
#   --readonly        (alleen client) maak het bestandssysteem na de installatie alleen-lezen
#   --skip-preflight  sla de voorcontrole over
#   -h, --help        deze uitleg
#
# Omgevingsvariabelen: KIOSK_USER (gebruiker voor het scherm, standaard degene die sudo gebruikte),
# WIFI_COUNTRY (standaard BE), ETH_IFACE (standaard eth0).
#
# Veilig om opnieuw uit te voeren: voor elk onderdeel wordt eerst gekeken of het er al staat, en alleen
# wat ontbreekt of verouderd is wordt (opnieuw) gedaan. Het is een nieuwe versie van de software? Dan wordt
# alleen de software vervangen en de dienst herstart.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/image/common.sh"

usage() {
  sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'
}

# ---------------------------------------------------------------- opties
ROLE=""
CHECK_ONLY=0
FORCE=0
READONLY=0
SKIP_PREFLIGHT="${SKIP_PREFLIGHT:-0}"
for arg in "$@"; do
  case "$arg" in
    server|client) ROLE="$arg" ;;
    --check) CHECK_ONLY=1 ;;
    --force) FORCE=1 ;;
    --readonly) READONLY=1 ;;
    --skip-preflight) SKIP_PREFLIGHT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "onbekende optie '$arg' (zie --help)" ;;
  esac
done
[ -n "$ROLE" ] || die "geef 'server' of 'client' op (zie --help)"
if [ "$READONLY" -eq 1 ] && [ "$ROLE" != client ]; then
  die "--readonly hoort alleen bij client"
fi

need_root
need_trixie

# ---------------------------------------------------------------- wat hoort bij welke rol
PACKAGES=(python3-venv python3-libgpiod iperf3 iw rfkill bluez network-manager dnsmasq-base curl)
OPTIONAL_PACKAGES=(libraspberrypi-bin)  # levert vcgencmd; zonder dit werkt de onderspanningsmeting niet
KIOSK_USER="${KIOSK_USER:-${SUDO_USER:-}}"
KIOSK_HOME="${KIOSK_HOME:-}"

if [ "$ROLE" = server ]; then
  PACKAGES+=(chromium)
  UNIT=rpitest-ui.service
  MY_IP="$(config_value SERVER_IP)"
  COMPONENTS=(packages app hostname pins wificountry login blanking kiosk unit network)
  if [ -z "$KIOSK_HOME" ] && [ -n "$KIOSK_USER" ] && id "$KIOSK_USER" >/dev/null 2>&1; then
    KIOSK_HOME="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
  fi
else
  UNIT=rpitest-agent.service
  MY_IP="$(config_value CLIENT_IP)"
  COMPONENTS=(packages app hostname pins wificountry unit network)
  [ "$READONLY" -eq 1 ] && COMPONENTS+=(readonly)
fi
[ -n "$MY_IP" ] || die "kon het IP-adres niet uit rpitest/config.py lezen (is python3 beschikbaar?)"

describe() {
  case "$1" in
    packages)    echo "Pakketten (apt)" ;;
    app)         echo "Software in $VENV" ;;
    hostname)    echo "Hostnaam test-$ROLE" ;;
    pins)        echo "GPIO-pinnen vrij (I2C, SPI en seriële poort uit)" ;;
    wificountry) echo "Wifi-land $WIFI_COUNTRY" ;;
    login)       echo "Automatisch inloggen op het bureaublad" ;;
    blanking)    echo "Schermbeveiliging uit (het scherm blijft aan)" ;;
    kiosk)       echo "Kioskbrowser bij het inloggen" ;;
    unit)        echo "Dienst $UNIT" ;;
    network)     echo "Vast IP-adres $MY_IP/24 op $ETH_IFACE" ;;
    readonly)    echo "Alleen-lezen bestandssysteem" ;;
  esac
}

# ---------------------------------------------------------------- controles per onderdeel
# Elke check_<naam> geeft 0 (aanwezig), 1 (ontbreekt of verouderd) of 2 (kan niet bepaald worden) terug
# en zet eventueel een korte toelichting in DETAIL. Elke apply_<naam> voert het onderdeel uit.
DETAIL=""
MISSING_PACKAGES=()
APP_CHANGED=0
UNIT_RESTARTED=0

MISSING_OPTIONAL=()

check_packages() {
  MISSING_PACKAGES=()
  MISSING_OPTIONAL=()
  local pkg
  for pkg in "${PACKAGES[@]}"; do
    package_installed "$pkg" || MISSING_PACKAGES+=("$pkg")
  done
  for pkg in "${OPTIONAL_PACKAGES[@]}"; do
    package_installed "$pkg" || MISSING_OPTIONAL+=("$pkg")
  done
  if [ "${#MISSING_PACKAGES[@]}" -gt 0 ]; then
    DETAIL="ontbreken: ${MISSING_PACKAGES[*]} ${MISSING_OPTIONAL[*]}"
    return 1
  fi
  # Een ontbrekend optioneel pakket telt niet mee: het wordt bij een installatie wel geprobeerd, maar als
  # het niet te installeren is mag het onderdeel niet bij elke run opnieuw 'ontbreekt' blijven geven.
  DETAIL="alle $((${#PACKAGES[@]})) aanwezig"
  [ "${#MISSING_OPTIONAL[@]}" -eq 0 ] || DETAIL="$DETAIL; optioneel ontbreekt: ${MISSING_OPTIONAL[*]}"
}

apply_packages() {
  local list=("${MISSING_PACKAGES[@]}" "${MISSING_OPTIONAL[@]}")
  [ "$FORCE" -eq 1 ] && list=("${PACKAGES[@]}" "${OPTIONAL_PACKAGES[@]}")
  [ "${#list[@]}" -gt 0 ] || return 0
  apt-get update || return 1
  # Het optionele pakket mag falen zonder dat de rest stopt.
  local required=() pkg
  for pkg in "${list[@]}"; do
    case " ${OPTIONAL_PACKAGES[*]} " in
      *" $pkg "*) apt-get install -y "$pkg" || warn "$pkg is niet te installeren (optioneel)" ;;
      *) required+=("$pkg") ;;
    esac
  done
  [ "${#required[@]}" -eq 0 ] || apt-get install -y "${required[@]}"
}

check_app() {
  local installed
  installed="$(cat "$APP_DIR/REVISION" 2>/dev/null)"
  if [ -x "$VENV/bin/python" ] && [ ! -x "$VENV/bin/pip" ]; then
    DETAIL="venv onvolledig (pip ontbreekt)"  # python3 -m venv maakt eerst python en pas dan pip
    return 1
  fi
  if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c "import rpitest, gpiod" 2>/dev/null; then
    DETAIL="nog niet geïnstalleerd (of rpitest/gpiod niet te importeren)"
    return 1
  fi
  if [ "$installed" != "$(repo_revision)" ]; then
    DETAIL="verouderd: draait ${installed:-een onbekende versie}, deze map bevat een andere"
    return 1
  fi
  DETAIL="revisie ${installed:0:8}"
}

apply_app() {
  mkdir -p "$APP_DIR" "$DATA_DIR/reports" || return 1
  # --system-site-packages: de module 'gpiod' komt uit het Debian-pakket python3-libgpiod
  # pip is het laatste dat de venv krijgt: ontbreekt het, dan is een eerdere poging halverwege mislukt (--clear begint opnieuw)
  [ -x "$VENV/bin/pip" ] || python3 -m venv --clear --system-site-packages "$VENV" || return 1
  "$VENV/bin/pip" install --upgrade --force-reinstall --no-deps "$REPO_DIR" || return 1
  "$VENV/bin/python" -c "import rpitest, gpiod" || { warn "rpitest of gpiod niet te importeren na de installatie"; return 1; }
  repo_revision > "$APP_DIR/REVISION"
  APP_CHANGED=1
}

check_hostname() {
  DETAIL="nu: $(hostname)"
  [ "$(hostname)" = "test-$ROLE" ]
}

apply_hostname() {
  local name="test-$ROLE"
  hostnamectl set-hostname "$name" || return 1
  # /etc/hosts bijwerken, anders klaagt sudo dat de hostnaam niet te vinden is
  if grep -q '^127\.0\.1\.1' "$HOSTS_FILE" 2>/dev/null; then
    sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t$name/" "$HOSTS_FILE"
  else
    printf '127.0.1.1\t%s\n' "$name" >> "$HOSTS_FILE"
  fi
}

# raspi-config nonint get_<x> geeft 0 (aan) of 1 (uit); iets anders betekent: kan het niet bepalen.
raspi_state() { raspi-config nonint "$1" 2>/dev/null; }

check_pins() {
  local get state unknown=0
  for get in get_i2c get_spi get_serial_hw get_serial_cons; do
    state="$(raspi_state "$get")"
    case "$state" in
      1) ;;
      0) DETAIL="$get meldt: staat aan"; return 1 ;;
      *) unknown=1 ;;
    esac
  done
  [ "$unknown" -eq 0 ] || { DETAIL="raspi-config geeft geen antwoord"; return 2; }
}

apply_pins() {
  local step ok=0
  for step in "do_i2c 1" "do_spi 1" "do_serial_hw 1" "do_serial_cons 1"; do
    # shellcheck disable=SC2086
    raspi-config nonint $step || { warn "raspi-config nonint $step mislukte"; ok=1; }
  done
  return "$ok"
}

check_wificountry() {
  command -v iw >/dev/null 2>&1 || { DETAIL="iw ontbreekt"; return 2; }
  iw reg get 2>/dev/null | grep -Eq "country $WIFI_COUNTRY(:| )"
}

apply_wificountry() {
  raspi-config nonint do_wifi_country "$WIFI_COUNTRY" || return 1
  rfkill unblock wifi || true
}

check_login() {
  case "$(raspi_state get_autologin)" in
    0) ;;
    1) DETAIL="automatisch inloggen staat uit"; return 1 ;;
    *) DETAIL="raspi-config geeft geen antwoord"; return 2 ;;
  esac
}

apply_login() {
  raspi-config nonint do_boot_behaviour B4 || { warn "automatisch inloggen instellen mislukte"; return 1; }
}

# Apart onderdeel (en niet bij 'login'): slaagt het ene en faalt het andere, dan moet alleen het mislukte
# bij de volgende run opnieuw. get_blanking geeft 0 (schermbeveiliging aan) of 1 (uit), zoals get_i2c.
check_blanking() {
  case "$(raspi_state get_blanking)" in
    1) ;;
    0) DETAIL="schermbeveiliging staat aan: het scherm wordt na enkele minuten zwart"; return 1 ;;
    *) DETAIL="raspi-config geeft geen antwoord"; return 2 ;;
  esac
}

apply_blanking() {
  raspi-config nonint do_blanking 1 || { warn "schermbeveiliging uitzetten mislukte"; return 1; }
}

check_kiosk() {
  if [ -z "$KIOSK_HOME" ]; then
    DETAIL="geen gebruiker bekend (geef KIOSK_USER=<naam> of start met sudo vanuit je gebruiker)"
    return 2
  fi
  # cmp geeft 2 terug als een bestand ontbreekt; voor ons is dat gewoon "ontbreekt" (1)
  cmp -s "$IMAGE_DIR/kiosk.sh" "$APP_DIR/kiosk.sh" || return 1
  grep -q "$APP_DIR/kiosk.sh" "$KIOSK_HOME/.config/labwc/autostart" 2>/dev/null || return 1
}

apply_kiosk() {
  [ -n "$KIOSK_HOME" ] || { warn "geen gebruiker voor het scherm: start met sudo vanuit je gebruiker, of geef KIOSK_USER=<naam>"; return 1; }
  mkdir -p "$APP_DIR" || return 1
  install -m 0755 "$IMAGE_DIR/kiosk.sh" "$APP_DIR/kiosk.sh" || return 1
  # Beide mappen met de juiste eigenaar aanmaken: bestond ~/.config nog niet, dan werd hij als root aangemaakt
  # en konden labwc en Chromium er na de automatische login niet in schrijven.
  install -d -o "$KIOSK_USER" -g "$KIOSK_USER" "$KIOSK_HOME/.config" "$KIOSK_HOME/.config/labwc" || return 1
  local autostart="$KIOSK_HOME/.config/labwc/autostart"
  # Een eigen autostart vervangt die van het bureaublad: geen taakbalk, enkel onze pagina. Een bestaande eigen
  # autostart wordt eenmalig bewaard als autostart.bak.
  if [ -f "$autostart" ] && ! grep -q "$APP_DIR/kiosk.sh" "$autostart" && [ ! -e "$autostart.bak" ]; then
    cp -p "$autostart" "$autostart.bak" || return 1
    warn "bestaande autostart bewaard als $autostart.bak"
  fi
  printf '%s\n' "$APP_DIR/kiosk.sh &" > "$autostart" || return 1
  chown "$KIOSK_USER:" "$autostart" 2>/dev/null || warn "eigenaar van $autostart niet aangepast"
}

check_unit() {
  systemctl is-enabled --quiet "$UNIT" 2>/dev/null || return 1
  cmp -s "$IMAGE_DIR/systemd/$UNIT" "$SYSTEMD_DIR/$UNIT" || return 1
}

apply_unit() {
  install -m 0644 "$IMAGE_DIR/systemd/$UNIT" "$SYSTEMD_DIR/$UNIT" || return 1
  systemctl daemon-reload && systemctl enable "$UNIT" || return 1
  systemctl restart "$UNIT" || warn "$UNIT startte niet meteen; zie: journalctl -u $UNIT"
  UNIT_RESTARTED=1
}

check_network() {
  local current
  current="$(nmcli -g ipv4.addresses connection show "$NM_PROFILE" 2>/dev/null)"
  DETAIL="nu: ${current:-geen profiel}"
  [ "$current" = "$MY_IP/24" ] || return 1
  # de diensten moeten dezelfde poort kiezen als dit profiel (zie rpitest/config.py, ETH_IFACE)
  [ "$(grep -s '^ETH_IFACE=' "$ETC_DIR/env")" = "ETH_IFACE=$ETH_IFACE" ] || { DETAIL="$DETAIL; $ETC_DIR/env wijkt af"; return 1; }
}

# Vast IP-adres op de rechtstreekse kabel (geen gateway: dit is alleen de testkabel). Dit gaat als laatste:
# het neemt de ethernetpoort over, dus geen internet meer via deze poort.
apply_network() {
  # zonder grep -q: dat sluit de pijp vroeg en geeft met 'pipefail' een vals negatief resultaat
  if nmcli -t -f NAME connection show | grep -x "$NM_PROFILE" >/dev/null; then
    nmcli connection delete "$NM_PROFILE" >/dev/null || return 1
  fi
  nmcli connection add type ethernet ifname "$ETH_IFACE" con-name "$NM_PROFILE" \
    ipv4.method manual ipv4.addresses "$MY_IP/24" ipv6.method disabled \
    connection.autoconnect yes connection.autoconnect-priority 100 >/dev/null || return 1
  # de diensten lezen dit bestand (EnvironmentFile), zodat zij dezelfde poort kiezen
  mkdir -p "$ETC_DIR" || return 1
  { grep -sv '^ETH_IFACE=' "$ETC_DIR/env"; echo "ETH_IFACE=$ETH_IFACE"; } > "$ETC_DIR/env.new" \
    && mv "$ETC_DIR/env.new" "$ETC_DIR/env" || return 1
  nmcli connection up "$NM_PROFILE" >/dev/null 2>&1 \
    || warn "profiel nog niet actief (geen kabel aangesloten?); het start vanzelf zodra er link is"
}

check_readonly() {
  DETAIL="de overlay is pas actief na een herstart"
  [ "$(findmnt -n -o FSTYPE / 2>/dev/null)" = overlay ]
}

apply_readonly() {
  raspi-config nonint enable_overlayfs && raspi-config nonint enable_bootro
}

# ---------------------------------------------------------------- weergave
status_line() {  # $1 toestand, $2 omschrijving, $3 toelichting
  local color
  case "$1" in
    aanwezig) color='1;32' ;;
    onbekend) color='1;33' ;;
    *) color='1;31' ;;
  esac
  printf '  \033[%sm[%-10s]\033[0m %s%s\n' "$color" "$1" "$2" "${3:+ ($3)}"
}

state_of() {
  case "$1" in
    0) echo aanwezig ;;
    2) echo onbekend ;;
    *) echo ontbreekt ;;
  esac
}

# ---------------------------------------------------------------- alleen controleren
if [ "$CHECK_ONLY" -eq 1 ]; then
  printf 'Wat staat er al op deze Pi? (rol: %s, wijzigt niets)\n\n' "$ROLE"
  missing=0
  unknown=0
  for component in "${COMPONENTS[@]}"; do
    DETAIL=""
    "check_$component" >/dev/null 2>&1
    rc=$?
    status_line "$(state_of "$rc")" "$(describe "$component")" "$DETAIL"
    [ "$rc" -eq 1 ] && missing=$((missing + 1))
    [ "$rc" -ge 2 ] && unknown=$((unknown + 1))
  done
  echo
  if [ "$missing" -gt 0 ]; then
    printf '%s onderdeel/onderdelen ontbreken of zijn verouderd. Voer uit: sudo ./install.sh %s\n' "$missing" "$ROLE"
    exit 3
  fi
  [ "$unknown" -eq 0 ] || printf '%s onderdeel/onderdelen konden niet bepaald worden.\n' "$unknown"
  echo "Alles wat gecontroleerd kon worden staat er al. Controleer verder met: sudo ./image/verify.sh $ROLE"
  exit 0
fi

# ---------------------------------------------------------------- installeren
if [ "$SKIP_PREFLIGHT" != 1 ]; then
  "$IMAGE_DIR/preflight.sh" "$ROLE" || die "de voorcontrole vond fouten; los ze op (of sla over met --skip-preflight)"
  echo
fi

APPLIED=()
SKIPPED=()
FAILED=()
for component in "${COMPONENTS[@]}"; do
  DETAIL=""
  "check_$component" >/dev/null 2>&1
  rc=$?
  if [ "$rc" -eq 0 ] && [ "$FORCE" -ne 1 ]; then
    status_line aanwezig "$(describe "$component")" "$DETAIL"
    SKIPPED+=("$component")
    continue
  fi
  log "$(describe "$component")"
  if "apply_$component"; then
    APPLIED+=("$component")
  else
    FAILED+=("$component")
    warn "mislukt: $(describe "$component")"
  fi
done

# Nieuwe software maar de dienst was al geïnstalleerd (en dus overgeslagen): herstart hem zodat hij de nieuwe code gebruikt.
if [ "$APP_CHANGED" -eq 1 ] && [ "$UNIT_RESTARTED" -ne 1 ]; then
  systemctl try-restart "$UNIT" || warn "kon $UNIT niet herstarten"
fi

echo
printf 'Gedaan: %s | al aanwezig: %s | mislukt: %s\n' "${#APPLIED[@]}" "${#SKIPPED[@]}" "${#FAILED[@]}"
if [ "${#FAILED[@]}" -gt 0 ]; then
  warn "niet gelukt: ${FAILED[*]}"
  warn "draai 'sudo ./image/diagnose.sh' en stuur het bestand mee als je hulp nodig hebt"
  exit 1
fi
echo
if [ "${#APPLIED[@]}" -eq 0 ]; then
  echo "Er was niets te doen: alles stond er al. Controleer met: sudo ./image/verify.sh $ROLE"
  exit 0
fi
echo "Volgende stappen:"
echo "  1. sudo reboot"
echo "  2. sudo ./image/verify.sh $ROLE"
[ "$ROLE" = server ] && echo "  3. sluit de netwerkkabel van de TEST-SERVER aan op de TEST-CLIENT (niet op het schoolnetwerk)"
exit 0
