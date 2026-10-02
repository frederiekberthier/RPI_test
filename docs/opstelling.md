# Opstelling: testpi + te testen Pi (breadboard)

```
 testpi (Pi 5, scherm)                              DUT (Pi 4/5, tester-SD)
 ┌──────────────┐   GPIO2..27 via 220 Ω       ┌──────────────┐
 │  header      ├─────────────────────────────┤  header      │
 │  GND         ├─────────────────────────────┤  GND         │
 │  eth0        ├──── UTP-kabel, 192.168.77.x ┤  eth0        │
 └──────────────┘                             └──────────────┘
 eigen voeding                                  eigen voeding
```

## Onderdelen

| Aantal | Onderdeel | Opmerking |
|---|---|---|
| 2 | 40-pins GPIO-breakout voor breadboard ("cobbler") + lintkabel | één per Pi |
| 2 | breadboard | één per breakout |
| 26 | weerstand 220 Ω | één per GPIO-lijn |
| 26 + 3 | male-male dupontdraad, ca. 20 cm | 26 signaal + 3 GND |
| 1 | UTP-kabel | direct tussen beide Pi's, geen switch |
| 2 | voeding per Pi (5 V / 3 A voor Pi 4, 5 V / 5 A voor Pi 5) | elke Pi zijn eigen voeding |
| 1 | multimeter | voor de controle voor de eerste keer opstarten |

## Veiligheidsregels

1. **Verbind nooit 3V3 of 5V tussen de twee Pi's.** Dat zijn de headerpinnen 1, 2, 4 en 17. Twee voedingen tegen elkaar kunnen een Pi kapotmaken. Enkel GND en de 26 GPIO's gaan over.
2. **Elke GPIO-lijn loopt via een weerstand van 220 Ω.** Zo blijft de stroom bij een softwarefout of een defecte pin beperkt tot ongeveer 15 mA (3,3 V / 220 Ω).
3. **Steek de GPIO-kabel alleen in of uit als beide Pi's uit staan.**
4. **Geen HAT's of andere hardware** op de header van de DUT tijdens de test.
5. GPIO0 en GPIO1 (pin 27 en 28, HAT-EEPROM) worden niet getest en niet verbonden.

## Bedrading

Verbind per GPIO de pin op breakout A (testpi) via een weerstand met dezelfde pin op breakout B (DUT).
Een weerstand past niet tussen twee breadboards. Zet hem daarom op breadboard A: één poot in het gat van de pin, de andere poot in een vrij gat van een andere kolom. Van die kolom loopt een dupontdraad naar de overeenkomstige pin op breadboard B.

Gebruik voor GND één draad op elk van drie GND-pinnen (bv. 6, 14, 39), zonder weerstand.

| GPIO | Pin | | GPIO | Pin | | GPIO | Pin |
|---|---|---|---|---|---|---|---|
| 2 | 3 | | 11 | 23 | | 20 | 38 |
| 3 | 5 | | 12 | 32 | | 21 | 40 |
| 4 | 7 | | 13 | 33 | | 22 | 15 |
| 5 | 29 | | 14 | 8 | | 23 | 16 |
| 6 | 31 | | 15 | 10 | | 24 | 18 |
| 7 | 26 | | 16 | 36 | | 25 | 22 |
| 8 | 24 | | 17 | 11 | | 26 | 37 |
| 9 | 21 | | 18 | 12 | | 27 | 13 |
| 10 | 19 | | 19 | 35 | | | |

GND-pinnen: 6, 9, 14, 20, 25, 30, 34, 39. De tabel staat ook in de code (`HEADER_PIN` in `rpitest/gpio/ports.py`), en een test controleert dat hij klopt. Het rapport noemt bij een probleem altijd GPIO-nummer én fysieke pin.

Tip: gebruik voor elke lijn de kleur van de weerstandsband of een label, zodat je bij een fout snel de juiste draad vindt.

## Controle voor het opstarten (beide Pi's uit)

Met de multimeter op doorgangstest:
- Elke GPIO-pin op A heeft doorgang (ca. 220 Ω) met dezelfde pin op B.
- Er is **geen** doorgang tussen twee verschillende GPIO-pinnen, ook niet tussen buurpinnen.
- Er is **geen** verbinding tussen 3V3 (pin 1, 17) of 5V (pin 2, 4) van A en B, en ook niet tussen deze pinnen en een GPIO of GND.
- GND van A heeft doorgang met GND van B.

## Netwerk

Rechtstreekse UTP-kabel tussen de twee ethernetpoorten, zonder crossoverkabel. Vaste adressen:

| | IP |
|---|---|
| testpi | 192.168.77.1 |
| DUT | 192.168.77.2 |

Op Raspberry Pi OS Trixie (NetworkManager). Dit zijn de commando's uit mijn geheugen, controleer ze bij de eerste keer:
```
sudo nmcli con add type ethernet ifname eth0 con-name rpitest \
     ipv4.method manual ipv4.addresses 192.168.77.1/24 ipv6.method disabled
sudo nmcli con up rpitest
```
Op de DUT-image hetzelfde met `192.168.77.2/24`. De adressen staan in `rpitest/config.py`.

## Software

Basis: **Raspberry Pi OS Lite (Trixie, 64-bit)**, voor beide Pi's. Bookworm werkt niet, want die levert libgpiod 1.x.

```
sudo apt install python3-libgpiod git
git clone https://github.com/frederiekberthier/RPI_test.git && cd RPI_test
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -e .
```

Zorg dat I2C, SPI en de seriële poort uit staan, anders houden ze pinnen bezet (bv. `sudo raspi-config nonint do_i2c 1`, `do_spi 1`, `do_serial_hw 1`, `do_serial_cons 1`, daarna herstarten).

**Op de DUT:**
```
python -m rpitest.agent --list-chips     # welke gpiochips zijn er?
python -m rpitest.agent                  # start de agent op 192.168.77.2:8765
```

**Op de testpi:**
```
python -m rpitest.agent --list-chips
python -m rpitest                        # voert de volledige test uit en maakt het rapport
```

## Eerste keer: wat nog bevestigd moet worden

Dit is geschreven zonder echte hardware. Controleer bij de eerste run:

1. **Chiplabels.** `--list-chips` moet op de Pi 5 een chip met label `pinctrl-rp1` (54 lijnen) tonen, en op de Pi 4 `pinctrl-bcm2711`. Wijkt het af, pas dan `HEADER_CHIP_LABELS` in `rpitest/gpio/real.py` aan.
2. **Zelftest met een bekend goede DUT.** Laat de test eerst draaien met een Pi waarvan je weet dat hij werkt. Een fout dan wijst op de bedrading of de testpi. Los die eerst op, voor je de eerste echte student-Pi test.
3. **GPIO2 en GPIO3.** Beide kanten hebben een vaste pull-up van 1,8 kΩ. Een lage stand komt via 220 Ω tegen één van die pull-ups uit, wat ongeveer 0,4 V geeft. Dat hoort ruim onder de drempel te liggen; controleer dat deze twee pinnen slagen.
4. **Pull-up/-down testen** (`gpio.pulls`): zwevende lijnen kunnen op echte hardware afwijken van de simulatie. Slagen alle pinnen, dan is dat goed. Zo niet, noteer dan welke.
