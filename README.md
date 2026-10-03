# GPIO_test
Test library om RPI hardwarematig te testen

## Opstelling
- **Testpi** (eigen Pi 5, met scherm): stuurt de test aan en maakt het rapport.
- **DUT** (te testen Pi 4/5): bootet van een eigen tester-SD met de agent.
- Verbonden met: GPIO-adapter (alleen GND + GPIO's, met serieweerstanden, géén 5V/3V3) en een
  rechtstreekse netwerkkabel met statische IP's.

![Overzicht van de opstelling](docs/img/overzicht.svg)

## Installeren op een Pi: stappenplan
Eén script (`install.sh`) doet alles: voorcontrole, pakketten (`apt`), software, hostnaam, vrije GPIO-pinnen, wifi-land,
scherm met kiosk (testpi), dienst en het vaste IP-adres. Het controleert per onderdeel eerst of het er al staat, dus je
kunt het veilig opnieuw uitvoeren. De stappen zijn voor de testpi en de DUT-SD hetzelfde; alleen `tester` of `dut` verschilt.

1. **Schrijf Raspberry Pi OS Trixie (64-bit)** naar een SD-kaart met Raspberry Pi Imager: *met bureaublad* voor de testpi,
   *Lite* voor de DUT-SD. Stel in de Imager een gebruiker, wifi (land `BE`) en SSH in.
2. **Start de Pi met internet** (via wifi, niet via de ethernetpoort die de testkabel wordt) en haal de software binnen:
   ```
   sudo apt install -y git
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   ```
3. **Kijk wat er al op de Pi staat** (optioneel, wijzigt niets):
   ```
   sudo ./install.sh tester --check        # of: dut
   ```
4. **Installeer** (voor het eerst ca. 5 tot 10 minuten):
   ```
   sudo ./install.sh tester                # of: dut
   ```
   Het script doet eerst een voorcontrole en stopt met een duidelijke melding als er iets ontbreekt.
5. **Herstart:** `sudo reboot`
6. **Controleer het resultaat:** `sudo ./image/verify.sh tester` (of `dut`)
7. **Iets mis?** `sudo ./image/diagnose.sh` verzamelt alle relevante uitvoer in één bestand om te delen.

| Optie | Wat het doet |
|---|---|
| `--check` | toont per onderdeel *aanwezig*, *ontbreekt* of *onbekend*; wijzigt niets |
| `--force` | past alles opnieuw toe, ook wat al aanwezig lijkt |
| `--readonly` | (alleen `dut`) maakt het bestandssysteem alleen-lezen na de installatie |
| `--skip-preflight` | slaat de voorcontrole over |

**Bijwerken** naar een nieuwe versie: `git pull && sudo ./install.sh tester`. Het script ziet dat alleen de software
verouderd is, vervangt die en herstart de dienst; de rest wordt overgeslagen.

Meer: [docs/eerste-installatie.md](docs/eerste-installatie.md) (draaiboek voor de eerste keer, met controlelijst),
[docs/image.md](docs/image.md) (scherm, diensten, SD klonen, probleemoplossing) en
[docs/opstelling.md](docs/opstelling.md) (onderdelen en bedrading van het breadboard).

## Ontwikkelen zonder hardware
```
pip install -e .[dev]
python -m pytest
python -m rpitest --mock                                   # gezonde gesimuleerde Pi
python -m rpitest.ui --mock                                # het scherm van de testpi, op http://127.0.0.1:8080
python -m rpitest --mock --fault stuck_low:D:5 --fault bridge:D:10:11 --fault open:7
python -m rpitest --mock --fault eth_100 --fault wifi_5g_dead --fault bt_dut_tx_dead
```
Faalspecificaties: `stuck_low|stuck_high:<T|D>:<pin>`, `bridge:<T|D>:<a>:<b>`, `open:<pin>`.
Systeemfouten: `eth_100`, `eth_errors`, `eth_slow`, `eth_loss`, `no_wifi`, `wifi_5g_dead`, `wifi_weak`,
`no_bt`, `bt_dut_rx_dead`, `bt_dut_tx_dead`, `tester_no_wifi`, `tester_no_bt`,
`usb_slotN_dead|usb2|corrupt|slow` (N = 1..4), `usb_no_sticks`, `usb_overcurrent`, `usb_disconnect`,
`power_undervolt`, `power_undervolt_history`, `power_hot`, `power_warm`, `power_throttle`, `power_cpu_error`,
`power_ram_error`, `power_core_missing`, `power_no_sensor`.

## Stand van zaken
Klaar: skelet, agent (JSON-RPC over HTTP), mock met foutinjectie, GPIO-checks, JSON/HTML-rapport,
echte GPIO-backend (libgpiod 2.x, enkel getest met een nep-`gpiod`), bedradingshandleiding,
netwerk-, wifi-, bluetooth-, USB- en voeding/temperatuurchecks (alleen getest met simulatie en nagebootste tooluitvoer).
Scherm met startknop en live resultaten (`rpitest.ui`), en één installatiescript voor tester en DUT (`install.sh`),
getest tegen nagebootste systeemopdrachten.
Nog te doen: alles op echte Pi's bevestigen (ook het installatiescript).
