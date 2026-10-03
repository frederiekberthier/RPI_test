"""Draait install.sh echt, maar tegen nagebootste systeemopdrachten (apt-get, dpkg-query, systemctl, nmcli,
raspi-config, ...) in een tijdelijke map. Zo testen we de logica 'is het al geïnstalleerd?' zonder een Pi.
Alle schrijfpaden (/opt, /etc, /var) wijzen in de test naar een tijdelijke map."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from bashutil import BASH

from rpitest import config

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(BASH is None, reason="geen werkende bash beschikbaar")

STUBS = {
    "id": '''
if [ "${1:-}" = "-u" ]; then echo "${FAKE_UID:-0}"; fi
exit 0
''',
    "dpkg-query": '''
pkg="${@: -1}"
if grep -qx "$pkg" "$STATE/dpkg" 2>/dev/null; then printf 'install ok installed'; else exit 1; fi
''',
    "apt-get": '''
echo "apt-get $*" >> "$STATE/calls"
if [ "${1:-}" = install ]; then
  for a in "$@"; do
    [ "$a" = "${FAIL_PACKAGE:-}" ] && exit 100
  done
  for a in "$@"; do
    case "$a" in install|-y) ;; *) echo "$a" >> "$STATE/dpkg" ;; esac
  done
fi
exit 0
''',
    "python3": '''
echo "python3 $*" >> "$STATE/calls"
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  target="${@: -1}"
  mkdir -p "$target/bin"
  printf '#!/usr/bin/env bash\\necho "venv-python $*" >> "$STATE/calls"\\n[ -f "$STATE/import_broken" ] && exit 1\\nexit 0\\n' > "$target/bin/python"
  printf '#!/usr/bin/env bash\\necho "pip $*" >> "$STATE/calls"\\nexit 0\\n' > "$target/bin/pip"
  chmod +x "$target/bin/python" "$target/bin/pip"
  exit 0
fi
exec "$REAL_PYTHON" "$@"
''',
    "git": '''
case " $* " in
  *" rev-parse "*) cat "$STATE/rev" 2>/dev/null || echo abc1234567890abcdef ;;
esac
exit 0
''',
    "hostname": 'cat "$STATE/hostname" 2>/dev/null || echo raspberrypi',
    "hostnamectl": '''
echo "hostnamectl $*" >> "$STATE/calls"
[ "${1:-}" = set-hostname ] && echo "$2" > "$STATE/hostname"
exit 0
''',
    "raspi-config": '''
echo "raspi-config $*" >> "$STATE/calls"
cmd="${2:-}"; arg="${3:-}"
[ "${FAIL_RASPI:-}" = "$cmd" ] && exit 1
case "$cmd" in
  get_i2c|get_spi|get_serial_hw|get_serial_cons|get_autologin|get_blanking)
    [ "${RASPI_UNKNOWN:-0}" = 1 ] && exit 0
    default=0; [ "$cmd" = get_autologin ] && default=1
    cat "$STATE/raspi_$cmd" 2>/dev/null || echo "$default" ;;
  do_i2c) echo "$arg" > "$STATE/raspi_get_i2c" ;;
  do_spi) echo "$arg" > "$STATE/raspi_get_spi" ;;
  do_serial_hw) echo "$arg" > "$STATE/raspi_get_serial_hw" ;;
  do_serial_cons) echo "$arg" > "$STATE/raspi_get_serial_cons" ;;
  do_boot_behaviour) echo 0 > "$STATE/raspi_get_autologin" ;;
  do_blanking) echo "$arg" > "$STATE/raspi_get_blanking" ;;
  do_wifi_country) echo "$arg" > "$STATE/country" ;;
esac
exit 0
''',
    "iw": '''
if [ "${1:-}" = reg ]; then printf 'global\\ncountry %s: DFS-ETSI\\n' "$(cat "$STATE/country" 2>/dev/null || echo 00)"; fi
exit 0
''',
    "rfkill": 'echo "rfkill $*" >> "$STATE/calls"; exit 0',
    "chown": "exit 0",
    # install (coreutils) zou -o/-g met echte gebruikers willen; hier alleen vastleggen en nabootsen
    "install": """
echo "install $*" >> "$STATE/calls"
mode=""; dir=0; args=()
while [ $# -gt 0 ]; do
  case "$1" in
    -m) mode="$2"; shift 2 ;;
    -o|-g) shift 2 ;;
    -d) dir=1; shift ;;
    *) args+=("$1"); shift ;;
  esac
done
if [ "$dir" = 1 ]; then mkdir -p "${args[@]}"; exit $?; fi
cp "${args[0]}" "${args[1]}" || exit 1
[ -n "$mode" ] && chmod "$mode" "${args[1]}"
exit 0
""",
    "findmnt": "echo ext4",
    "systemctl": '''
echo "systemctl $*" >> "$STATE/calls"
case "${1:-}" in
  is-enabled) [ -f "$STATE/enabled_${@: -1}" ]; exit $? ;;
  enable) touch "$STATE/enabled_${2}" ;;
esac
exit 0
''',
    "nmcli": '''
echo "nmcli $*" >> "$STATE/calls"
case "$*" in
  "-g ipv4.addresses connection show rpitest") cat "$STATE/nm_ip" 2>/dev/null; exit 0 ;;
  "-t -f NAME connection show") [ -f "$STATE/nm_profile" ] && echo rpitest; exit 0 ;;
  "connection delete rpitest") rm -f "$STATE/nm_profile" "$STATE/nm_ip"; exit 0 ;;
esac
if [ "${1:-} ${2:-}" = "connection add" ]; then
  prev=""
  for a in "$@"; do [ "$prev" = ipv4.addresses ] && echo "$a" > "$STATE/nm_ip"; prev="$a"; done
  touch "$STATE/nm_profile"
fi
exit 0
''',
}

# opdrachten die iets wijzigen: na een volledige installatie mogen die niet opnieuw voorkomen
MUTATING = re.compile(
    r"^(apt-get |python3 -m venv|pip |install |hostnamectl |rfkill |raspi-config nonint (do_|enable_)|"
    r"nmcli connection (add|delete|up)|systemctl (enable|restart|try-restart|daemon-reload))")


class Sandbox:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.state = tmp_path / "state"
        self.bin = tmp_path / "bin"
        for directory in (self.state, self.bin, tmp_path / "systemd", tmp_path / "home"):
            directory.mkdir()
        for name, body in STUBS.items():
            stub = self.bin / name
            stub.write_text("#!/usr/bin/env bash\n" + body.lstrip("\n"), newline="\n")
            stub.chmod(0o755)  # zonder uitvoerrechten slaat bash de stub op Linux over en draait het echte commando
        (tmp_path / "os-release").write_text("VERSION_CODENAME=trixie\n")
        (tmp_path / "hosts").write_text("127.0.0.1\tlocalhost\n127.0.1.1\traspberrypi\n")
        self.packages = ["python3-venv", "python3-libgpiod", "iperf3", "iw", "rfkill", "bluez", "network-manager",
                         "dnsmasq-base", "curl", "chromium", "libraspberrypi-bin"]

    def env(self, **extra):
        env = dict(os.environ)
        env.update({
            "PATH": f"{self.bin};{os.environ['PATH']}" if os.name == "nt" else f"{self.bin}:{os.environ['PATH']}",
            "STATE": self.state.as_posix(),
            "APP_DIR": (self.root / "app").as_posix(),
            "DATA_DIR": (self.root / "data").as_posix(),
            "SYSTEMD_DIR": (self.root / "systemd").as_posix(),
            "ETC_DIR": (self.root / "etc").as_posix(),
            "HOSTS_FILE": (self.root / "hosts").as_posix(),
            "OS_RELEASE_FILE": (self.root / "os-release").as_posix(),
            "KIOSK_USER": "kiosk",
            "KIOSK_HOME": (self.root / "home").as_posix(),
            "REAL_PYTHON": Path(sys.executable).as_posix(),
        })
        env.update(extra)
        return env

    def install_packages(self, *names):
        existing = self.state / "dpkg"
        existing.write_text("\n".join(names) + "\n")

    def assert_stubs_are_used(self, env):
        """Weiger te draaien als een systeemcommando niet naar de stub wijst: de echte zouden het systeem wijzigen."""
        probe = subprocess.run([BASH, "-c", "command -v " + " ".join(STUBS)], env=env, capture_output=True, text=True,
                               check=False)
        found = probe.stdout.split()
        wrong = [line for line in found if self.root.name not in line]
        assert len(found) == len(STUBS) and not wrong, f"stubs niet actief, echte commando's: {wrong or probe.stderr}"

    def run(self, *args, **env):
        full_env = self.env(**env)
        self.assert_stubs_are_used(full_env)
        result = subprocess.run([BASH, (ROOT / "install.sh").as_posix(), *args], cwd=ROOT, env=full_env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        result.clean = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout + result.stderr)
        return result

    def calls(self):
        path = self.state / "calls"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def mutations(self):
        return [c for c in self.calls() if MUTATING.match(c)]


@pytest.fixture
def box(tmp_path):
    return Sandbox(tmp_path)


def installed_state(box, role="server", *args):
    result = box.run(role, "--skip-preflight", *args)
    assert result.returncode == 0, result.clean
    return result


# ---------------------------------------------------------------- alleen controleren

def test_check_mode_on_an_empty_pi_reports_missing_and_changes_nothing(box):
    result = box.run("server", "--check")
    assert result.returncode == 3, result.clean
    assert "ontbreekt" in result.clean and "ontbreken: python3-venv" in result.clean
    # alles ontbreekt echt: er is niets "onbekend" (regressie: cmp gaf 2 terug bij een ontbrekend bestand)
    assert "[onbekend" not in result.clean and result.clean.count("[ontbreekt") == 10
    assert "Voer uit: sudo ./install.sh server" in result.clean
    assert box.mutations() == []
    assert not (box.root / "app" / "REVISION").exists() and not list((box.root / "systemd").iterdir())


def test_check_mode_after_installing_says_everything_is_there(box):
    installed_state(box)
    result = box.run("server", "--check")
    assert result.returncode == 0, result.clean
    assert result.clean.count("[aanwezig") == 10 and "ontbreekt " not in result.clean.replace("ontbreken", "")


# ---------------------------------------------------------------- eerste installatie

def test_first_install_does_everything_in_a_sensible_order(box):
    result = installed_state(box)
    calls = box.calls()
    assert "apt-get update" in calls
    install_call = next(c for c in calls if c.startswith("apt-get install -y python3-venv"))
    for pkg in ("python3-libgpiod", "iperf3", "iw", "bluez", "network-manager", "dnsmasq-base", "curl", "chromium"):
        assert pkg in install_call
    assert any(c.startswith("python3 -m venv --clear --system-site-packages") for c in calls)
    assert sum(c.startswith("pip install --upgrade --force-reinstall --no-deps") for c in calls) == 1
    assert "hostnamectl set-hostname test-server" in calls
    for step in ("do_i2c 1", "do_spi 1", "do_serial_hw 1", "do_serial_cons 1", "do_wifi_country BE",
                 "do_boot_behaviour B4", "do_blanking 1"):
        assert f"raspi-config nonint {step}" in calls, step
    assert "systemctl enable rpitest-ui.service" in calls
    assert f"ipv4.addresses {config.SERVER_IP}/24" in next(c for c in calls if c.startswith("nmcli connection add"))
    # het netwerk gaat als laatste: daarna zijn er geen wijzigende opdrachten meer
    last_mutation = box.mutations()[-1]
    assert last_mutation.startswith("nmcli connection up"), last_mutation
    assert "Volgende stappen" in result.clean and "sudo reboot" in result.clean
    assert (box.root / "systemd" / "rpitest-ui.service").read_bytes() == (
        ROOT / "image/systemd/rpitest-ui.service").read_bytes()
    assert (box.root / "app" / "REVISION").read_text().strip() == "abc1234567890abcdef"
    assert (box.root / "data" / "reports").is_dir()
    autostart = (box.root / "home" / ".config" / "labwc" / "autostart").read_text()
    assert autostart.strip() == f"{(box.root / 'app').as_posix()}/kiosk.sh &"
    assert (box.root / "app" / "kiosk.sh").read_bytes() == (ROOT / "image/kiosk.sh").read_bytes()
    assert "127.0.1.1\ttest-server" in (box.root / "hosts").read_text()


# ---------------------------------------------------------------- is het al geïnstalleerd?

def test_second_run_recognises_everything_and_does_nothing(box):
    installed_state(box)
    before = len(box.mutations())
    result = box.run("server", "--skip-preflight")
    assert result.returncode == 0, result.clean
    assert len(box.mutations()) == before, box.mutations()[before:]  # niets opnieuw gedaan
    assert "Gedaan: 0 | al aanwezig: 10 | mislukt: 0" in result.clean
    assert "niets te doen" in result.clean and "sudo reboot" not in result.clean  # geen onnodige herstart-tip


def test_only_the_missing_packages_are_installed(box):
    box.install_packages(*[p for p in box.packages if p not in ("iperf3", "chromium")])
    box.run("server", "--skip-preflight")
    installs = [c for c in box.calls() if c.startswith("apt-get install")]
    assert installs == ["apt-get install -y iperf3 chromium"]


def test_all_packages_present_means_apt_is_not_touched(box):
    box.install_packages(*box.packages)
    box.run("server", "--skip-preflight")
    assert not [c for c in box.calls() if c.startswith("apt-get")]


def test_a_new_revision_replaces_only_the_software_and_restarts_the_service(box):
    installed_state(box)
    before = len(box.calls())
    (box.state / "rev").write_text("nieuwe-revisie-0001\n")
    result = box.run("server", "--skip-preflight")
    new = box.calls()[before:]
    assert sum(c.startswith("pip install") for c in new) == 1
    assert "systemctl try-restart rpitest-ui.service" in new
    assert not [c for c in new if c.startswith(("apt-get", "hostnamectl", "nmcli connection"))]
    assert (box.root / "app" / "REVISION").read_text().strip() == "nieuwe-revisie-0001"
    assert "Gedaan: 1 | al aanwezig: 9" in result.clean


def test_a_deleted_unit_file_counts_as_missing_not_unknown(box):
    installed_state(box)
    (box.root / "systemd" / "rpitest-ui.service").unlink()
    result = box.run("server", "--check")
    assert result.returncode == 3 and "[ontbreekt ] Dienst rpitest-ui.service" in result.clean
    assert "[onbekend" not in result.clean


def test_check_mode_flags_an_outdated_version(box):
    installed_state(box)
    (box.state / "rev").write_text("nieuwe-revisie-0002\n")
    result = box.run("server", "--check")
    assert result.returncode == 3 and "verouderd" in result.clean


def test_a_broken_import_in_the_venv_counts_as_not_installed(box):
    installed_state(box)
    (box.state / "import_broken").write_text("x")
    result = box.run("server", "--check")
    assert result.returncode == 3 and "niet te importeren" in result.clean


def test_force_reapplies_everything(box):
    installed_state(box)
    before = len(box.calls())
    box.run("server", "--skip-preflight", "--force")
    new = box.calls()[before:]
    assert any(c.startswith("apt-get install -y") for c in new)
    assert any(c.startswith("pip install") for c in new) and "hostnamectl set-hostname test-server" in new
    assert any(c.startswith("nmcli connection add") for c in new)


# ---------------------------------------------------------------- de TEST-CLIENT

def test_client_gets_the_agent_but_no_kiosk(box):
    box.run("client", "--skip-preflight")
    calls = box.calls()
    assert "systemctl enable rpitest-agent.service" in calls
    assert "systemctl enable rpitest-ui.service" not in calls
    assert not [c for c in calls if "do_boot_behaviour" in c or "chromium" in c]
    assert f"ipv4.addresses {config.CLIENT_IP}/24" in next(c for c in calls if c.startswith("nmcli connection add"))
    assert "hostnamectl set-hostname test-client" in calls
    assert not (box.root / "home" / ".config").exists()


def test_readonly_is_only_allowed_for_the_client(box):
    result = box.run("server", "--readonly", "--skip-preflight")
    assert result.returncode != 0 and "alleen bij client" in result.clean
    assert box.mutations() == []
    box.run("client", "--readonly", "--skip-preflight")
    assert "raspi-config nonint enable_overlayfs" in box.calls()


# ---------------------------------------------------------------- onzekerheid en fouten

def test_unknown_raspi_config_answers_are_reapplied_instead_of_trusted(box):
    result = box.run("server", "--check", RASPI_UNKNOWN="1")
    assert "[onbekend" in result.clean
    box.run("server", "--skip-preflight", RASPI_UNKNOWN="1")
    assert "raspi-config nonint do_i2c 1" in box.calls()


def test_one_failing_component_is_reported_but_the_rest_still_runs(box):
    result = box.run("server", "--skip-preflight", FAIL_PACKAGE="iperf3")
    assert result.returncode == 1
    assert "niet gelukt: packages" in result.clean and "diagnose.sh" in result.clean
    assert "hostnamectl set-hostname test-server" in box.calls()  # de rest ging door
    assert "Volgende stappen" not in result.clean


def test_a_failed_component_is_retried_on_the_next_run(box):
    box.run("server", "--skip-preflight", FAIL_PACKAGE="iperf3")
    result = box.run("server", "--skip-preflight")
    assert result.returncode == 0, result.clean
    assert "iperf3" in (box.state / "dpkg").read_text()


# ---------------------------------------------------------------- bescherming

def test_refuses_anything_but_trixie(box):
    (box.root / "os-release").write_text("VERSION_CODENAME=bookworm\n")
    result = box.run("server", "--check")
    assert result.returncode != 0 and "Trixie" in result.clean and "bookworm" in result.clean
    assert box.mutations() == []


def test_requires_root(box):
    result = box.run("server", "--check", FAKE_UID="1000")
    assert result.returncode != 0 and "sudo" in result.clean


def test_bad_arguments(box):
    assert "onbekende optie" in box.run("server", "--zomaar").clean
    result = box.run("--check")
    assert result.returncode != 0 and "server' of 'client" in result.clean
    help_text = box.run("--help")
    assert help_text.returncode == 0 and "--check" in help_text.clean and "sudo ./install.sh server" in help_text.clean


# ---------------------------------------------------------------- issue #7: dezelfde interface in install en dienst

def test_the_chosen_interface_is_written_for_the_services(box):
    box.run("server", "--skip-preflight", ETH_IFACE="enp3s0")
    env_file = box.root / "etc" / "env"
    assert "ETH_IFACE=enp3s0" in env_file.read_text()
    add = next(c for c in box.calls() if c.startswith("nmcli connection add"))
    assert "ifname enp3s0" in add


def test_an_outdated_interface_in_the_env_file_counts_as_missing(box):
    installed_state(box)
    (box.root / "etc" / "env").write_text("ETH_IFACE=eth9\n")
    result = box.run("server", "--check")
    assert result.returncode == 3 and "[ontbreekt ] Vast IP-adres" in result.clean


def test_both_units_read_the_env_file():
    for unit in sorted((ROOT / "image/systemd").glob("*.service")):
        assert "EnvironmentFile=-/etc/rpitest/env" in unit.read_text(), unit.name


# ---------------------------------------------------------------- issue #23: half aangemaakte venv

def make_half_venv(box):
    """Zoals `python3 -m venv` die halverwege faalt: bin/python bestaat, pip niet."""
    bin_dir = box.root / "app" / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_text("#!/usr/bin/env bash\nexit 0\n", newline="\n")
    python.chmod(0o755)
    return bin_dir


def test_a_venv_without_pip_counts_as_not_installed(box):
    make_half_venv(box)
    result = box.run("server", "--check")
    assert result.returncode == 3 and "[ontbreekt ] Software" in result.clean and "pip ontbreekt" in result.clean


def test_a_half_created_venv_is_rebuilt_instead_of_skipped(box):
    bin_dir = make_half_venv(box)
    result = box.run("server", "--skip-preflight")
    assert result.returncode == 0, result.clean
    assert any(c.startswith("python3 -m venv --clear --system-site-packages") for c in box.calls())
    assert (bin_dir / "pip").exists()


# ---------------------------------------------------------------- issue #24: schermbeveiliging apart en herhaalbaar

def test_a_failed_blanking_step_is_retried_on_the_next_run(box):
    first = box.run("server", "--skip-preflight", FAIL_RASPI="do_blanking")
    assert first.returncode == 1 and "niet gelukt: blanking" in first.clean
    second = box.run("server", "--skip-preflight")
    assert second.returncode == 0, second.clean
    assert sum(c == "raspi-config nonint do_blanking 1" for c in box.calls()) == 2  # niet als 'aanwezig' overgeslagen
    assert box.run("server", "--check").returncode == 0


def test_autologin_and_blanking_are_reported_separately(box):
    result = box.run("server", "--check")
    assert "Automatisch inloggen op het bureaublad" in result.clean and "Schermbeveiliging uit" in result.clean


def test_the_client_needs_neither_autologin_nor_blanking(box):
    result = box.run("client", "--check")
    assert "Schermbeveiliging" not in result.clean and "Automatisch inloggen" not in result.clean


# ---------------------------------------------------------------- issue #25: eigenaar van ~/.config

def test_config_directories_are_created_for_the_kiosk_user_not_for_root(box):
    box.run("server", "--skip-preflight")
    home = (box.root / "home").as_posix()
    assert f"install -d -o kiosk -g kiosk {home}/.config {home}/.config/labwc" in box.calls()


def test_an_existing_custom_autostart_is_backed_up_once(box):
    autostart = box.root / "home" / ".config" / "labwc" / "autostart"
    autostart.parent.mkdir(parents=True)
    autostart.write_text("mijn-eigen-paneel &\n")
    box.run("server", "--skip-preflight")
    backup = autostart.with_name("autostart.bak")
    assert backup.read_text() == "mijn-eigen-paneel &\n"
    assert "kiosk.sh" in autostart.read_text()
    box.run("server", "--skip-preflight", "--force")  # opnieuw toepassen mag de back-up niet overschrijven
    assert backup.read_text() == "mijn-eigen-paneel &\n"


# ---------------------------------------------------------------- issue #26: optioneel pakket

def test_an_optional_package_that_cannot_be_installed_does_not_keep_the_pi_in_the_missing_state(box):
    first = box.run("server", "--skip-preflight", FAIL_PACKAGE="libraspberrypi-bin")
    assert first.returncode == 0, first.clean
    second = box.run("server", "--skip-preflight")
    assert second.returncode == 0 and "niets te doen" in second.clean, second.clean
    check = box.run("server", "--check")
    assert check.returncode == 0 and "optioneel" in check.clean and "libraspberrypi-bin" in check.clean


def test_a_missing_optional_package_is_still_tried_during_a_normal_install(box):
    box.run("server", "--skip-preflight")
    assert "libraspberrypi-bin" in (box.state / "dpkg").read_text()


def test_missing_required_packages_still_fail_the_check(box):
    box.install_packages(*[p for p in box.packages if p != "iperf3"])
    result = box.run("server", "--check")
    assert result.returncode == 3 and "ontbreken: iperf3" in result.clean
