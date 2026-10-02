# GPIO_test
Test library om RPI hardwarematig te testen

## Opstelling
- **Testpi** (eigen Pi 5, met scherm): stuurt de test aan en maakt het rapport.
- **DUT** (te testen Pi 4/5): bootet van een eigen tester-SD met de agent.
- Verbonden met: GPIO-adapter (alleen GND + GPIO's, met serieweerstanden, géén 5V/3V3) en een
  rechtstreekse netwerkkabel met statische IP's.

## Ontwikkelen zonder hardware
```
pip install -e .[dev]
python -m pytest
python -m rpitest --mock                                   # gezonde gesimuleerde Pi
python -m rpitest --mock --fault stuck_low:D:5 --fault bridge:D:10:11 --fault open:7
python -m rpitest --mock --fault eth_100 --fault wifi_5g_dead --fault bt_dut_tx_dead
```
Faalspecificaties: `stuck_low|stuck_high:<T|D>:<pin>`, `bridge:<T|D>:<a>:<b>`, `open:<pin>`.
Systeemfouten: `eth_100`, `eth_errors`, `eth_slow`, `eth_loss`, `no_wifi`, `wifi_5g_dead`, `wifi_weak`,
`no_bt`, `bt_dut_rx_dead`, `bt_dut_tx_dead`, `tester_no_wifi`, `tester_no_bt`,
`usb_slotN_dead|usb2|corrupt|slow` (N = 1..4), `usb_no_sticks`, `usb_overcurrent`, `usb_disconnect`,
`power_undervolt`, `power_undervolt_history`, `power_hot`, `power_warm`, `power_throttle`, `power_cpu_error`,
`power_ram_error`, `power_core_missing`, `power_no_sensor`.

## Op echte hardware
Zie [docs/opstelling.md](docs/opstelling.md): onderdelen, bedrading van het breadboard,
netwerk, installatie (Raspberry Pi OS **Trixie**, libgpiod 2.x) en wat bij de eerste run nog
bevestigd moet worden.

## Stand van zaken
Klaar: skelet, agent (JSON-RPC over HTTP), mock met foutinjectie, GPIO-checks, JSON/HTML-rapport,
echte GPIO-backend (libgpiod 2.x, enkel getest met een nep-`gpiod`), bedradingshandleiding,
netwerk-, wifi-, bluetooth-, USB- en voeding/temperatuurchecks (alleen getest met simulatie en nagebootste tooluitvoer).
Nog te doen: alles op echte Pi's bevestigen, tester-image, scherm/kiosk.
