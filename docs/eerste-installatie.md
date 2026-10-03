# Eerste installatie: stap voor stap

Dit draaiboek loop je één keer door om de testopstelling voor het eerst op echte hardware op te zetten.
Elke stap zegt wat je ziet als het goed gaat. Alles is tot nu toe alleen in simulatie getest, dus verwacht dat er een
paar dingen afwijken. Daarom bestaan **`preflight.sh`** (vooraf), **`verify.sh`** (achteraf) en **`diagnose.sh`**
(verzamelt de ruwe uitvoer van alle tools, om naar de ontwikkelaar te sturen).

Plan ongeveer een uur, de bedrading niet meegerekend.

## 0. Wat je nodig hebt

- [ ] TEST-SERVER: Pi 5, voeding (5 V / 5 A), SD-kaart (16 GB of meer), HDMI-scherm, toetsenbord, internet (wifi)
- [ ] Een **bekend goede** Pi 4 of 5 als eerste TEST-CLIENT, met voeding, en een SD-kaart (8 tot 16 GB) voor de TEST-CLIENT
- [ ] De breadboards met de 26 weerstandskabels en 3 GND-draden, gebouwd volgens [opstelling.md](opstelling.md)
- [ ] UTP-kabel, en de USB-fixture met 4 voorbereide sticks (stap 4 van [opstelling.md](opstelling.md)); de USB-test mag je eerst overslaan
- [ ] Een ventilator voor de TEST-CLIENT (temperatuurmetingen)
- [ ] Een USB-stick om bestanden mee over te brengen (of `scp`)

## 1. De TEST-SERVER

1. Schrijf **Raspberry Pi OS (64-bit, Trixie, met bureaublad)** met Raspberry Pi Imager. In de instellingen: hostnaam
   `test-server`, een gebruiker met wachtwoord, wifi met land `BE`, SSH aan.
2. Start de Pi met scherm en toetsenbord. Hij moet internet hebben via wifi.
3. Haal de software binnen:
   ```
   sudo apt install -y git
   git clone https://github.com/frederiekberthier/RPI_test.git
   cd RPI_test
   ```
4. **Voorcontrole:**
   ```
   ./image/preflight.sh server
   ```
   Je wilt `Geen fouten` zien. Waarschuwingen (`[let op]`) mogen, zoals "geen scherm op HDMI herkend" als je dat
   nog niet hebt aangesloten. Bij `[FOUT]` staat er wat je moet doen; los dat op en draai het opnieuw.
5. **Installeren** (5 tot 10 minuten):
   ```
   sudo ./install.sh server
   sudo reboot
   ```
6. Na de herstart logt de Pi vanzelf in en toont het scherm **"Raspberry Pi tester"** met **"Wachten op de TEST-CLIENT…"**.
7. **Natest** (via SSH of een terminal, de TEST-CLIENT hoeft nog niet aan te staan):
   ```
   cd RPI_test && sudo ./image/verify.sh server
   ```
   Alles moet `[ok]` zijn. Verwachte `[let op]`-regels nu: het vaste IP-adres staat er niet zonder kabel op, en de TEST-CLIENT
   antwoordt nog niet.

Lukt de natest of het scherm niet, ga dan naar stap 5 en stuur de diagnose.

## 2. De TEST-CLIENT-SD

1. Schrijf **Raspberry Pi OS Lite (Trixie)** naar een SD, hostnaam `test-client`, een gebruiker, wifi voor de installatie, SSH aan.
2. Start de TEST-CLIENT (nog **zonder** testkabels) en haal de software binnen zoals bij de TEST-SERVER.
3. ```
   ./image/preflight.sh client
   sudo ./install.sh client
   sudo reboot
   sudo ./image/verify.sh client        # na de herstart
   ```
   Gebruik **nog geen** `--readonly`: dat doe je pas als alles werkt (stap 6), want daarna zijn wijzigingen weg.
4. Haal de SD uit de TEST-CLIENT en bewaar hem als je TEST-CLIENT-SD.

## 3. Bedrading en eerste verbinding

1. Beide Pi's **uit**. Bouw en controleer de bedrading met de multimeter, volgens [opstelling.md](opstelling.md).
2. Sluit de GPIO-kabels aan, de UTP-kabel tussen beide ethernetpoorten, en eventueel de USB-fixture.
3. Steek de TEST-CLIENT-SD in de TEST-CLIENT. Zet eerst de **TEST-SERVER** aan, daarna de **TEST-CLIENT**, met een ventilator op de TEST-CLIENT.
4. Na ca. een halve minuut staat op het scherm **"TEST-CLIENT verbonden"** met model en serienummer, en wordt de knop groen.
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
2. Maak de TEST-CLIENT-SD alleen-lezen: `sudo ./install.sh client --readonly`, herstart, en controleer met `verify.sh client`
   (je ziet dan een `[let op]` dat de overlay actief is: zo hoort het).
3. Kloon de SD ([image.md](image.md)) zodat je meerdere identieke TEST-CLIENT-SD's hebt.
