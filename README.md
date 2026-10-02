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
```
Faalspecificaties: `stuck_low|stuck_high:<T|D>:<pin>`, `bridge:<T|D>:<a>:<b>`, `open:<pin>`.

## Stand van zaken
Klaar: skelet, agent (JSON-RPC over HTTP), mock met foutinjectie, GPIO-checks, JSON/HTML-rapport.
Nog te doen: echte GPIO-backend (gpiod), netwerk, USB, wifi, Bluetooth, voeding/temperatuur,
tester-image, scherm/kiosk.
