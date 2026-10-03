# Installatie en scherm van de TEST-SERVER

De TEST-SERVER toont via HDMI een scherm met de testresultaten en een grote startknop. De TEST-CLIENT
start met een eigen SD-kaart waarop de agent automatisch draait. Beide worden gemaakt met een script op een
kale Raspberry Pi OS; daarna kun je de SD klonen.

**Dagelijks gebruik:**

1. Steek de **TEST-CLIENT-SD** in de TEST-CLIENT, sluit GPIO-kabels, netwerkkabel en USB-fixture aan en zet hem aan.
2. Op het scherm van de TEST-SERVER staat na ca. een halve minuut **"TEST-CLIENT verbonden"** met model en serienummer, en wordt de knop groen.
3. Druk op **START TEST** (of op Enter / spatie, of op een grote USB-knop die een toets stuurt).
4. De voortgang verschijnt live. Na ca. 4 minuten staat er een groot **Geslaagd / Niet geslaagd**, met de problemen bovenaan.
5. Het rapport (HTML en JSON) is dan al opgeslagen. Druk op **NIEUWE TEST** voor de volgende Pi.

De knop is pas actief als de TEST-CLIENT bereikbaar is. **Afbreken** stopt na het onderdeel dat bezig is;
het rapport is dan **Onvolledig**.

**Voor het eerst op echte hardware?** Volg dan het draaiboek in [eerste-installatie.md](eerste-installatie.md).
De scripts `image/preflight.sh` (voorcontrole), `image/verify.sh` (natest) en `image/diagnose.sh` (verzamelt de ruwe
uitvoer van alle tools om terug te sturen) horen daarbij; ze wijzigen niets.

## Wat je nodig hebt

- TEST-SERVER: Pi 5 met scherm op HDMI, toetsenbord of USB-knop. Raspberry Pi OS **Trixie, 64-bit, mét bureaublad**.
- TEST-CLIENT-SD: Raspberry Pi OS **Trixie** (Lite is genoeg), een kleine SD (8 tot 16 GB) kloont sneller.
- Voor de installatie: internet via wifi of een USB-ethernetadapter. Niet via de ethernetpoort die voor de testkabel bedoeld is.

Bookworm werkt niet: dat levert libgpiod 1.x. De scripts weigeren te draaien op iets anders dan Trixie.

## Installeren: stappenplan

De stappen zijn voor de TEST-SERVER en de TEST-CLIENT-SD hetzelfde; alleen het woord `server` of `client` verschilt. Het volledige
stappenplan staat ook in de [README](../README.md#installeren-op-een-pi-stappenplan).

1. Schrijf Raspberry Pi OS **Trixie, 64-bit** naar een SD met Raspberry Pi Imager: **met bureaublad** voor de TEST-SERVER,
   **Lite** voor de TEST-CLIENT-SD (een kleine SD van 8 tot 16 GB kloont sneller). Stel gebruiker, wifi (land `BE`) en SSH in.
2. Start de Pi met internet via wifi en haal de software binnen:
   ```
   sudo apt install -y git
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   ```
3. Kijk wat er al staat (wijzigt niets): `sudo ./install.sh server --check`
4. Installeer: `sudo ./install.sh server` (voor de TEST-CLIENT: `sudo ./install.sh client`)
5. Herstart: `sudo reboot`. Het scherm van de TEST-SERVER start dan vanzelf.
6. Controleer: `sudo ./image/verify.sh server` (of `client`)

**Wat `install.sh` doet**, in deze volgorde en alleen voor wat nog ontbreekt of verouderd is:

| Onderdeel | TEST-SERVER | TEST-CLIENT |
|---|---|---|
| voorcontrole (`image/preflight.sh`) | ja | ja |
| pakketten via `apt` (alleen de ontbrekende) | ja, plus `chromium` | ja |
| software in `/opt/rpitest/venv` (gebouwd met het Debian-pakket `python3-setuptools`, dus zonder PyPI) | ja | ja |
| hostnaam `test-server` / `test-client` | ja | ja |
| I2C, SPI en seriële console uit | ja | ja |
| wifi-land (standaard `BE`) | ja | ja |
| automatisch inloggen op het bureaublad | ja | nee |
| schermbeveiliging uit (apart onderdeel, wordt bij een mislukking opnieuw geprobeerd) | ja | nee |
| kioskbrowser bij het inloggen | ja | nee |
| dienst `rpitest-ui` / `rpitest-agent` | ja | ja |
| vast IP-adres (als laatste) | `.1` | `.2` |
| alleen-lezen bestandssysteem | nee | met `--readonly` |

**Opties:** `--check` (alleen tonen), `--force` (alles opnieuw), `--readonly` (alleen `client`), `--skip-preflight`.
Omgevingsvariabelen: `KIOSK_USER`, `WIFI_COUNTRY`, `ETH_IFACE`. Geef ze na `sudo` mee, in de vorm `sudo VARIABELE=waarde ./install.sh server`:
`VARIABELE=waarde sudo ./install.sh server` werkt niet, want sudo gooit variabelen van je eigen shell weg.

**Is de software al geïnstalleerd?** Het script bepaalt dat per onderdeel: pakketten via `dpkg-query`, de software via de
`REVISION` die bij de installatie is vastgelegd, de dienst via `systemctl` en het IP-adres via NetworkManager. Draai je het script
opnieuw, dan staat er `[aanwezig]` bij wat klaar is, en wordt dat overgeslagen. Haal je een nieuwe versie van de repo binnen
(`git pull`), dan wordt alleen de software vervangen en de dienst herstart.

**Alleen-lezen TEST-CLIENT-SD:** pas dit toe als alles werkt, met `sudo ./install.sh client --readonly`. Een Pi die zonder afsluiten
uitgezet wordt, kan de SD dan niet meer beschadigen, maar wijzigingen gaan na een herstart verloren. Schakel de overlay eerst
uit (`raspi-config`, Performance Options) om bij te werken.

**Kloon de TEST-CLIENT-SD** als hij klaar is, zodat je meerdere identieke kaarten hebt:
```
sudo dd if=/dev/sdX of=client-master.img bs=4M status=progress
```
Schrijf `client-master.img` met Imager of `dd` naar elke nieuwe SD.

## Wat waar staat

| Wat | Waar |
|---|---|
| Software | `/opt/rpitest/venv` |
| Rapporten (HTML + JSON) | `/var/lib/rpitest/reports` op de TEST-SERVER |
| Diensten | `rpitest-ui` (TEST-SERVER), `rpitest-agent` (TEST-CLIENT) |
| IP-adressen | `rpitest/config.py` (TEST-SERVER `.1`, TEST-CLIENT `.2`); de scripts lezen ze daar |
| Gekozen netwerkpoort (`ETH_IFACE`) | `/etc/rpitest/env`, door `install.sh` geschreven en door beide diensten gelezen; de ingebouwde `eth0` heeft voorrang op USB-adapters |
| Extra opties voor het scherm | `/etc/rpitest/ui.env`, bv. `RPITEST_UI_ARGS=--usb-fixture /etc/rpitest/usb_fixture.json` |
| Logboek | `journalctl -u rpitest-ui` of `journalctl -u rpitest-agent` |

**Rapporten ophalen:** steek een USB-stick in de TEST-SERVER en kopieer de map, of gebruik `scp` via wifi.
Elk rapport is een zelfstandige HTML-pagina (`report-<serienummer>-<tijd>.html`) met daarnaast een JSON-bestand.

## Veiligheid

- Het scherm luistert alleen op `127.0.0.1`. Tijdens de wifi-test opent de TEST-SERVER een hotspot; de startknop en de
  uitschakelknop zijn daar niet bereikbaar. Verzoeken met een vreemde `Host`-header worden geweigerd.
- Rapporten worden alleen onder hun eigen bestandsnaam geserveerd; er is geen manier om andere bestanden te lezen.
- Tekst die van de TEST-CLIENT komt (namen van usb-apparaten, wifi-netwerken) wordt altijd als tekst getoond, nooit als HTML.
- De dienst draait als root (wifi-hotspot, bluetooth en GPIO vragen dat). De agent op de TEST-CLIENT draait ook als root en
  heeft een vaste lijst opdrachten met gecontroleerde parameters.
- De knop **TEST-SERVER uitschakelen** onderaan vraagt bevestiging en werkt niet tijdens een test.

## Als iets niet werkt

| Symptoom | Kijk naar |
|---|---|
| Scherm blijft zwart of toont een foutpagina | `systemctl status rpitest-ui`; draait het bureaublad met automatisch inloggen (`raspi-config`)? Test lokaal: `curl http://127.0.0.1:8080/api/state` |
| "Wachten op de TEST-CLIENT" blijft staan | Op de TEST-CLIENT: `systemctl status rpitest-agent` (zonder kabel wacht de agent tot het vaste adres bestaat: `journalctl -u rpitest-agent`); de netwerkkabel (rechtstreeks, geen switch); `ip addr` op beide Pi's; `curl http://192.168.77.2:8765` vanaf de TEST-SERVER geeft een antwoord als de agent draait |
| Test faalt met "GPIO-lijnen in gebruik" | I2C, SPI of de seriële console staan aan, of er draait nog een andere `rpitest`; herstart de dienst |
| Alles geeft FAIL na een bedradingsfout | Voer de zelftest uit met een bekend goede Pi (zie `docs/opstelling.md`) |
| Browser start niet | `journalctl --user` en `ls ~/.config/labwc/autostart`; controleer de naam van het Chromium-programma (`chromium` of `chromium-browser`) |

## Wat nog niet op echte hardware is bevestigd

De scripts zijn geschreven en op syntaxis en onderlinge consistentie getest, maar nog **niet op een Pi uitgevoerd**.
Controleer bij de eerste keer:

1. De pakketnamen (`chromium`, `libraspberrypi-bin`, `dnsmasq-base`, `python3-libgpiod`) op Trixie.
2. De `raspi-config nonint`-opdrachten: `do_boot_behaviour B4` (bureaublad met automatisch inloggen), `do_blanking 1`,
   `do_wifi_country`, `enable_overlayfs` en `enable_bootro`. Het script meldt een waarschuwing als er een mislukt.
3. De autostart van labwc (`~/.config/labwc/autostart`). Ik ga ervan uit dat die de standaard autostart vervangt
   (geen taakbalk). Verschijnt de taakbalk toch, of start de browser niet, dan zit het probleem hier.
4. Schermbeveiliging: `install.sh` zet die uit via `raspi-config nonint do_blanking 1` en controleert dat met `get_blanking` (0 = aan,
   1 = uit; de betekenis is nog niet op Trixie bevestigd). Wordt het scherm toch na enkele minuten zwart, meld dat dan.
5. De kiosk-opties van Chromium (`--ozone-platform-hint=auto` en de rest) op de Chromium-versie van Trixie.
6. Of de installatie als root over SSH via wifi niet vastloopt wanneer het vaste IP-adres aan het eind wordt gezet.
