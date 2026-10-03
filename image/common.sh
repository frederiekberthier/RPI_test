#!/usr/bin/env bash
# Gedeelde functies en vaste afspraken voor install.sh, preflight.sh, verify.sh en diagnose.sh.
# Wordt gesourced, niet los gestart. Alle paden zijn overschrijfbaar via de omgeving (voor tests).

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

IMAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$IMAGE_DIR/.." && pwd)"
APP_DIR="${APP_DIR:-/opt/rpitest}"
VENV="$APP_DIR/venv"
DATA_DIR="${DATA_DIR:-/var/lib/rpitest}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
HOSTS_FILE="${HOSTS_FILE:-/etc/hosts}"
OS_RELEASE_FILE="${OS_RELEASE_FILE:-/etc/os-release}"
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
    server|client) ;;
    *) die "gebruik: $0 server|client" ;;
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
  codename="$(. "$OS_RELEASE_FILE" 2>/dev/null && echo "${VERSION_CODENAME:-}")"
  if [ "$codename" != "trixie" ]; then
    die "dit werkt alleen op Raspberry Pi OS Trixie (gevonden: ${codename:-onbekend}); Bookworm heeft libgpiod 1.x"
  fi
}

# Waarden uit de Python-configuratie halen, zodat IP-adressen maar op een plaats staan (rpitest/config.py).
config_value() {
  (cd "$REPO_DIR" && python3 -c "from rpitest import config; print(config.$1)")
}

# Is dit Debian-pakket geïnstalleerd?
package_installed() {
  [ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null)" = "install ok installed" ]
}

# Welke versie van de software staat in deze map? Een uitgecheckte, ongewijzigde commit geeft een vaste
# waarde; bij onopgeslagen wijzigingen (of zonder git) is de waarde nooit gelijk aan de vorige, zodat
# er dan altijd opnieuw geïnstalleerd wordt.
repo_revision() {
  local git=(git -c "safe.directory=$REPO_DIR" -C "$REPO_DIR") rev
  rev="$("${git[@]}" rev-parse HEAD 2>/dev/null)" || { echo "onbekend-$(date +%s)"; return; }
  if [ -n "$("${git[@]}" status --porcelain 2>/dev/null)" ]; then
    rev="$rev-gewijzigd-$(date +%s)"
  fi
  echo "$rev"
}
