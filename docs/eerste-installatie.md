# Eerste installatie: stap voor stap

Dit draaiboek loop je één keer door om de testopstelling voor het eerst op echte hardware op te zetten.
Elke stap zegt wat je ziet als het goed gaat. Alles is tot nu toe alleen in simulatie getest, dus verwacht dat er een
paar dingen afwijken. Daarom bestaan **`preflight.sh`** (vooraf), **`verify.sh`** (achteraf) en **`diagnose.sh`**
(verzamelt de ruwe uitvoer van alle tools, om naar de ontwikkelaar te sturen).

Plan ongeveer een uur, de bedrading niet meegerekend.

## 0. Wat je nodig hebt

- [ ] Testpi: Pi 5, voeding (5 V / 5 A), SD-kaart (16 GB of meer), HDMI-scherm, toetsenbord, internet (wifi)
- [ ] Een **bekend goede** Pi 4 of 5 als eerste DUT, met voeding, en een SD-kaart (8 tot 16 GB) voor de DUT
- [ ] De breadboards met de 26 weerstandskabels en 3 GND-draden, gebouwd volgens [opstelling.md](opstelling.md)
- [ ] UTP-kabel, en de USB-fixture met 4 voorbereide sticks (stap 4 van [opstelling.md](opstelling.md)); de USB-test mag je eerst overslaan
- [ ] Een ventilator voor de DUT (temperatuurmetingen)
- [ ] Een USB-stick om bestanden mee over te brengen (of `scp`)

## 1. De testpi

1. Schrijf **Raspberry Pi OS (64-bit, Trixie, met bureaublad)** met Raspberry Pi Imager. In de instellingen: hostnaam
   `rpitest-tester`, een gebruiker met wachtwoord, wifi met land `BE`, SSH aan.
2. Start de Pi met scherm en toetsenbord. Hij moet internet hebben via wifi.
3. Haal de software binnen:
   ```
   sudo apt install -y git
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   ```
4. **Voorcontrole:**
   ```
   ./image/preflight.sh tester
   ```
   Je wilt `Geen fouten` zien. Waarschuwingen (`[let op]`) mogen, zoals "geen scherm op HDMI herkend" als je dat
   nog niet hebt aangesloten. Bij `[FOUT]` staat er wat je moet doen; los dat op en draai het opnieuw.
5. **Installeren** (5 tot 10 minuten):
   ```
   sudo ./install.sh tester
   sudo reboot
   ```
6. Na de herstart logt de Pi vanzelf in en toont het scherm **"Raspberry Pi tester"** met **"Wachten op de DUT…"**.
7. **Natest** (via SSH of een terminal, de DUT hoeft nog niet aan te staan):
   ```
   cd RPI_test && sudo ./image/verify.sh tester
   ```
   Alles moet `[ok]` zijn. Verwachte `[let op]`-regels nu: het vaste IP-adres staat er niet zonder kabel op, en de DUT
   antwoordt nog niet.

Lukt de natest of het scherm niet, ga dan naar stap 5 en stuur de diagnose.

## 2. De DUT-SD

1. Schrijf **Raspberry Pi OS Lite (Trixie)** naar een SD, hostnaam `rpitest-dut`, een gebruiker, wifi voor de installatie, SSH aan.
2. Start de DUT (nog **zonder** testkabels) en haal de software binnen zoals bij de testpi.
3. ```
   ./image/preflight.sh dut
   sudo ./install.sh dut
   sudo reboot
   sudo ./image/verify.sh dut        # na de herstart
   ```
   Gebruik **nog geen** `--readonly`: dat doe je pas als alles werkt (stap 6), want daarna zijn wijzigingen weg.
4. Haal de SD uit de DUT en bewaar hem als je tester-SD.

## 3. Bedrading en eerste verbinding

1. Beide Pi's **uit**. Bouw en controleer de bedrading met de multimeter, volgens [opstelling.md](opstelling.md).
2. Sluit de GPIO-kabels aan, de UTP-kabel tussen beide ethernetpoorten, en eventueel de USB-fixture.
3. Steek de tester-SD in de DUT. Zet eerst de **testpi** aan, daarna de **DUT**, met een ventilator op de DUT.
4. Na ca. een halve minuut staat op het scherm **"DUT verbonden"** met model en serienummer, en wordt de knop groen.
   Blijft het "Wachten", kijk dan in [image.md](image.md) onder "Als iets niet werkt".

## 4. De eerste test, met een bekend goede Pi

Druk op **START TEST**. Reken op ongeveer 4 minuten. Een bekend goede Pi hoort ver te komen, maar **verwacht dat niet alles
meteen slaagt**: dat is juist wat deze eerste run moet boven water brengen. Let op:

| Als je ziet | Dan is het waarschijnlijk |
|---|---|
| veel GPIO-pinnen falen, of dezelfde pinnen als je andere Pi | een bedradingsfout of een kapotte weerstandskabel |
| `GPIO2` en `GPIO3` falen als enige | de weerstandswaarde bij die twee pinnen; zie "Eerste keer" in [opstelling.md](opstelling.md) |
| `usb.fixture` of een slot ontbreekt | de fixture is niet aangesloten of de sticks zijn niet voorbereid |
| wifi of bluetooth in `FAIL` met een vreemde melding | een parser die het echte formaat niet kent: stuur de diagnose |
| waarschuwingen voor temperatuur of snelheid | drempels uit `rpitest/config.py` die nog geijkt moeten worden |

Open daarna het HTML-rapport (**HTML-rapport openen**) en bewaar het.

## 5. Terugsturen: de diagnose

Draai op **beide** Pi's, bij voorkeur met alles aangesloten en de test net gedaan:

```
sudo ./image/diagnose.sh
```

Het schrijft één bestand `/tmp/rpitest-diagnose-<naam>-<tijd>.txt` en toont waar. Het bevat o.a. serienummer, MAC-adressen en
namen van wifi-netwerken en bluetooth-apparaten in de buurt, maar geen wachtwoorden. Het bestand duurt ca. 30 seconden
(het scant kort wifi en bluetooth).

Stuur mee:
- beide diagnosebestanden, en het HTML- en JSON-rapport van de eerste run (`/var/lib/rpitest/reports`);
- welke Pi's je gebruikte (model, RAM) en wat je als eerste zag dat afweek.

Met die ruwe uitvoer controleer ik de parsers en aannames (chiplabels, `nmcli`, `iw`, `bluetoothctl`, `vcgencmd`,
USB-paden) en pas ik de code aan.

## 6. Afronden

Als alles werkt:

1. Stel de drempels in `rpitest/config.py` bij op basis van wat de bekend goede Pi haalde (snelheden, signaalsterkte, temperatuur).
2. Maak de DUT-SD alleen-lezen: `sudo ./install.sh dut --readonly`, herstart, en controleer met `verify.sh dut`
   (je ziet dan een `[let op]` dat de overlay actief is: zo hoort het).
3. Kloon de SD ([image.md](image.md)) zodat je meerdere identieke tester-SD's hebt.
