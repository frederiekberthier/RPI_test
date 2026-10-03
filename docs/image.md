# Tester-image en scherm

De testpi toont via HDMI een scherm met de testresultaten en een grote startknop. De te testen Pi (DUT)
start met een eigen SD-kaart waarop de agent automatisch draait. Beide worden gemaakt met een script op een
kale Raspberry Pi OS; daarna kun je de SD klonen.

**Dagelijks gebruik:**

1. Steek de **tester-SD** in de te testen Pi, sluit GPIO-kabels, netwerkkabel en USB-fixture aan en zet hem aan.
2. Op het scherm van de testpi staat na ca. een halve minuut **"DUT verbonden"** met model en serienummer, en wordt de knop groen.
3. Druk op **START TEST** (of op Enter / spatie, of op een grote USB-knop die een toets stuurt).
4. De voortgang verschijnt live. Na ca. 4 minuten staat er een groot **Geslaagd / Niet geslaagd**, met de problemen bovenaan.
5. Het rapport (HTML en JSON) is dan al opgeslagen. Druk op **NIEUWE TEST** voor de volgende Pi.

De knop is pas actief als de DUT bereikbaar is. **Afbreken** stopt na het onderdeel dat bezig is;
het rapport is dan **Onvolledig**.

## Wat je nodig hebt

- Testpi: Pi 5 met scherm op HDMI, toetsenbord of USB-knop. Raspberry Pi OS **Trixie, 64-bit, mét bureaublad**.
- DUT-SD: Raspberry Pi OS **Trixie** (Lite is genoeg), een kleine SD (8 tot 16 GB) kloont sneller.
- Voor de installatie: internet via wifi of een USB-ethernetadapter. Niet via de ethernetpoort die voor de testkabel bedoeld is.

Bookworm werkt niet: dat levert libgpiod 1.x. De scripts weigeren te draaien op iets anders dan Trixie.

## De testpi maken

1. Schrijf Raspberry Pi OS (Trixie, 64-bit, met bureaublad) met Raspberry Pi Imager. Maak een gebruiker aan, stel wifi in en zet SSH aan.
2. Start de Pi, zorg voor internet en haal de software binnen:
   ```
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   sudo ./image/install-tester.sh
   sudo reboot
   ```
3. Het script installeert de pakketten, de software (`/opt/rpitest`), zet automatisch inloggen aan, laat de kioskbrowser
   starten, installeert de dienst `rpitest-ui` en zet als laatste het vaste IP-adres op de ethernetpoort.
   Via `KIOSK_USER=<naam>` en `WIFI_COUNTRY=BE` stel je de gebruiker en het wifi-land in.

Na de herstart start het scherm vanzelf. Opnieuw uitvoeren van het script werkt de software bij.

## De DUT-SD maken

1. Schrijf Raspberry Pi OS Lite (Trixie) naar een SD, met een gebruiker en internet voor de installatie.
2. ```
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   sudo ./image/install-dut.sh --readonly     # zonder --readonly blijft de SD beschrijfbaar
   sudo reboot
   ```
   `--readonly` zet een overlay aan: een Pi die zonder afsluiten uitgezet wordt, kan de SD niet meer beschadigen.
   Wijzigingen na de herstart gaan verloren. Schakel de overlay eerst uit (`raspi-config`, Performance Options) om bij te werken.
3. **Kloon de SD** als hij klaar is, zodat je meerdere identieke kaarten hebt:
   ```
   sudo dd if=/dev/sdX of=dut-master.img bs=4M status=progress
   ```
   Schrijf `dut-master.img` met Imager of `dd` naar elke nieuwe SD.

## Wat waar staat

| Wat | Waar |
|---|---|
| Software | `/opt/rpitest/venv` |
| Rapporten (HTML + JSON) | `/var/lib/rpitest/reports` op de testpi |
| Diensten | `rpitest-ui` (testpi), `rpitest-agent` (DUT) |
| IP-adressen | `rpitest/config.py` (testpi `.1`, DUT `.2`); de scripts lezen ze daar |
| Extra opties voor het scherm | `/etc/rpitest/ui.env`, bv. `RPITEST_UI_ARGS=--usb-fixture /etc/rpitest/usb_fixture.json` |
| Logboek | `journalctl -u rpitest-ui` of `journalctl -u rpitest-agent` |

**Rapporten ophalen:** steek een USB-stick in de testpi en kopieer de map, of gebruik `scp` via wifi.
Elk rapport is een zelfstandige HTML-pagina (`report-<serienummer>-<tijd>.html`) met daarnaast een JSON-bestand.

## Veiligheid

- Het scherm luistert alleen op `127.0.0.1`. Tijdens de wifi-test opent de testpi een hotspot; de startknop en de
  uitschakelknop zijn daar niet bereikbaar. Verzoeken met een vreemde `Host`-header worden geweigerd.
- Rapporten worden alleen onder hun eigen bestandsnaam geserveerd; er is geen manier om andere bestanden te lezen.
- Tekst die van de DUT komt (namen van usb-apparaten, wifi-netwerken) wordt altijd als tekst getoond, nooit als HTML.
- De dienst draait als root (wifi-hotspot, bluetooth en GPIO vragen dat). De agent op de DUT draait ook als root en
  heeft een vaste lijst opdrachten met gecontroleerde parameters.
- De knop **Testpi uitschakelen** onderaan vraagt bevestiging en werkt niet tijdens een test.

## Als iets niet werkt

| Symptoom | Kijk naar |
|---|---|
| Scherm blijft zwart of toont een foutpagina | `systemctl status rpitest-ui`; draait het bureaublad met automatisch inloggen (`raspi-config`)? Test lokaal: `curl http://127.0.0.1:8080/api/state` |
| "Wachten op de DUT" blijft staan | Op de DUT: `systemctl status rpitest-agent`; de netwerkkabel (rechtstreeks, geen switch); `ip addr` op beide Pi's; `curl http://192.168.77.2:8765` vanaf de testpi geeft een antwoord als de agent draait |
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
4. Schermbeveiliging: als het scherm na enkele minuten zwart wordt, moet dat apart worden uitgezet.
5. De kiosk-opties van Chromium (`--ozone-platform-hint=auto` en de rest) op de Chromium-versie van Trixie.
6. Of de installatie als root over SSH via wifi niet vastloopt wanneer het vaste IP-adres aan het eind wordt gezet.
