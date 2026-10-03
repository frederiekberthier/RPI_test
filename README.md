# GPIO_test
Test library om RPI hardwarematig te testen

## Opstelling
- **TEST-SERVER** (eigen Pi 5, met scherm): stuurt de test aan en maakt het rapport.
- **TEST-CLIENT** (de te testen Pi 4/5): bootet van een eigen TEST-CLIENT-SD met de agent.
- Verbonden met: GPIO-adapter (alleen GND + GPIO's, met serieweerstanden, géén 5V/3V3) en een
  rechtstreekse netwerkkabel met statische IP's.

![Overzicht van de opstelling](docs/img/overzicht.svg)

**Namen:** de twee Pi's heten **TEST-SERVER** en **TEST-CLIENT**. Aan de scripts geef je `server` of `client` mee
(`./install.sh server`); de hostnamen worden `test-server` en `test-client`. De namen gaan over de Pi's, niet over het
netwerkprotocol: de agent op de TEST-CLIENT is technisch een HTTP-server en de TEST-SERVER roept hem aan.
"Raspberry Pi tester" is de naam van de applicatie.

## Installeren op een Pi: stappenplan
Eén script (`install.sh`) doet alles: voorcontrole, pakketten (`apt`), software, hostnaam, vrije GPIO-pinnen, wifi-land,
scherm met kiosk (TEST-SERVER), dienst en het vaste IP-adres. Het controleert per onderdeel eerst of het er al staat, dus je
kunt het veilig opnieuw uitvoeren. De stappen zijn voor de TEST-SERVER en de TEST-CLIENT-SD hetzelfde; alleen `server` of `client` verschilt.

1. **Schrijf Raspberry Pi OS Trixie (64-bit)** naar een SD-kaart met Raspberry Pi Imager: *met bureaublad* voor de TEST-SERVER,
   *Lite* voor de TEST-CLIENT-SD. Stel in de Imager een gebruiker, wifi (land `BE`) en SSH in.
2. **Start de Pi met internet** (via wifi, niet via de ethernetpoort die de testkabel wordt) en haal de software binnen:
   ```
   sudo apt install -y git
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   ```
3. **Kijk wat er al op de Pi staat** (optioneel, wijzigt niets):
   ```
   sudo ./install.sh server --check        # of: client
   ```
4. **Installeer** (voor het eerst ca. 5 tot 10 minuten):
   ```
   sudo ./install.sh server                # of: client
   ```
   Het script doet eerst een voorcontrole en stopt met een duidelijke melding als er iets ontbreekt.
5. **Herstart:** `sudo reboot`
6. **Controleer het resultaat:** `sudo ./image/verify.sh server` (of `client`)
7. **Iets mis?** `sudo ./image/diagnose.sh` verzamelt alle relevante uitvoer in één bestand om te delen.

| Optie | Wat het doet |
|---|---|
| `--check` | toont per onderdeel *aanwezig*, *ontbreekt* of *onbekend*; wijzigt niets |
| `--force` | past alles opnieuw toe, ook wat al aanwezig lijkt |
| `--readonly` | (alleen `client`) maakt het bestandssysteem alleen-lezen na de installatie |
| `--skip-preflight` | slaat de voorcontrole over |

**Bijwerken** naar een nieuwe versie: `git pull && sudo ./install.sh server`. Het script ziet dat alleen de software
verouderd is, vervangt die en herstart de dienst; de rest wordt overgeslagen.

Meer: [docs/eerste-installatie.md](docs/eerste-installatie.md) (draaiboek voor de eerste keer, met controlelijst),
[docs/image.md](docs/image.md) (scherm, diensten, SD klonen, probleemoplossing) en
[docs/opstelling.md](docs/opstelling.md) (onderdelen en bedrading van het breadboard).

## Ontwikkelen zonder hardware
```
pip install -e .[dev]
python -m pytest
python -m rpitest --mock                                   # gezonde gesimuleerde Pi
python -m rpitest.ui --mock                                # het scherm van de TEST-SERVER, op http://127.0.0.1:8080
python -m rpitest --mock --fault stuck_low:C:5 --fault bridge:C:10:11 --fault open:7
python -m rpitest --mock --fault eth_100 --fault wifi_5g_dead --fault bt_client_tx_dead
```
Faalspecificaties: `stuck_low|stuck_high:<S|C>:<pin>`, `bridge:<S|C>:<a>:<b>`, `open:<pin>`.
Systeemfouten: `eth_100`, `eth_errors`, `eth_slow`, `eth_loss`, `no_wifi`, `wifi_5g_dead`, `wifi_weak`,
`no_bt`, `bt_client_rx_dead`, `bt_client_tx_dead`, `server_no_wifi`, `server_no_bt`,
`usb_slotN_dead|usb2|corrupt|slow` (N = 1..4), `usb_no_sticks`, `usb_overcurrent`, `usb_disconnect`,
`power_undervolt`, `power_undervolt_history`, `power_hot`, `power_warm`, `power_throttle`, `power_cpu_error`,
`power_ram_error`, `power_core_missing`, `power_no_sensor`.

## Stand van zaken
Klaar: skelet, agent (JSON-RPC over HTTP), mock met foutinjectie, GPIO-checks, JSON/HTML-rapport,
echte GPIO-backend (libgpiod 2.x, enkel getest met een nep-`gpiod`), bedradingshandleiding,
netwerk-, wifi-, bluetooth-, USB- en voeding/temperatuurchecks (alleen getest met simulatie en nagebootste tooluitvoer).
Scherm met startknop en live resultaten (`rpitest.ui`), en één installatiescript voor server en TEST-CLIENT (`install.sh`),
getest tegen nagebootste systeemopdrachten.
Nog te doen: alles op echte Pi's bevestigen (ook het installatiescript).
