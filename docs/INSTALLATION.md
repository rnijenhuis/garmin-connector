# Installatie op Ubuntu

## Werkende configuratie

Vastgelegd op 4 november 2026. Identifiers zijn configuratiegegevens, geen wachtwoorden; houd deze handleiding toch privé vanwege de infrastructuurdetails.

| Onderdeel | Waarde |
|---|---|
| Project | `~/Documents-Prive/Projects/garmin-connector` |
| Tunnelprofiel | `garmin-plus` |
| Tunnel ID | `tunnel_6ae7a0e2af9c8191aeafabc40bcc648d` |
| OpenAI Organization ID | `org-9ENwHB5TGd84UsFzcKujMFas` |
| Tunnel-client tijdens de test / lokaal gecontroleerd | `0.0.19` |
| Approval-origin | `https://robert-pc.tail8c36bd.ts.net` |
| Lokale approval-server | `127.0.0.1:8788` |
| Browsergebruikersnaam | `owner` |

De eigenaar heeft activiteiten lezen en browsergoedgekeurde upload via ChatGPT succesvol getest. Dit is geen bevestiging van live planning of device-push. Op een nieuwe computer veranderen pad, Tailscale-hostnaam en mogelijk accountkoppelingen; neem die niet blind over.

## 1. Project en Python

Installeer de Ubuntu-basisgereedschappen:

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip curl
mkdir -p ~/Documents-Prive/Projects
```

Clone de eigen repository naar `~/Documents-Prive/Projects/garmin-connector` met de werkelijke private repository-URL, of kopieer de broncode veilig. Er is geen repository-URL in deze handleiding ingevuld. Kopieer geen oude `.venv`, tokens of approval-state mee als broncode.

```bash
cd ~/Documents-Prive/Projects/garmin-connector
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py preview
timeout 45s .venv/bin/python -m unittest discover -s tests -v
```

De bestaande omgeving gebruikt Python 3.14.4, garminconnect 0.3.20, MCP SDK 2.3.0, Starlette 1.10.0 en Uvicorn 0.54.0. Een Ubuntu-standaardinterpreter is niet automatisch dezelfde geteste versie. Als dependencies daarop niet installeren, provision dan een passende Python-versie en maak daarmee de venv; wijzig niet zomaar de pins. Node/npm is alleen nodig voor de optionele [Inspector](REFERENCE.md#mcp-inspector), niet voor de tunnelroute.

## 2. Garmin-sessie handmatig maken

Voer zelf uit in een privéterminal:

```bash
.venv/bin/python test_garmin.py
chmod 700 ~/.garminconnect
```

Dit leest echte Garmin-activiteiten, vraagt e-mail, wachtwoord en eventueel MFA, en bewaart sessies buiten de repo. Gebruik een wachtwoordmanager; plak uitvoer of sessiebestanden niet in chat. MCP gebruikt uitsluitend deze opgeslagen sessie en vraagt nooit credentials op STDIO. Imports en serverstart authenticeren niet.

## 3. Browserwachtwoord instellen

```bash
.venv/bin/python -m garmin_connector.browser_approval --setup
```

Kies een uniek wachtwoord van minimaal 20 tekens, anders dan Garmin/OpenAI. De twee verborgen prompts moeten overeenkomen. Gebruikersnaam is vast `owner`. De broncode bewaart uitsluitend een willekeurig 32-byte salt en 64-byte scrypt-digest (`n=16384, r=8, p=1`) in `~/.config/garmin-connector/browser-auth.json`, nieuw bestand mode 600, nieuwe bovenliggende map mode 700. `--auth-file` kan een ander pad buiten de repo kiezen. Setup overschrijft geen bestaand bestand. Zie [rotatie](TROUBLESHOOTING.md#geheimen-vervangen).

## 4. Tailscale en private HTTPS

Installeer Tailscale volgens de [Ubuntu/Linux-installatiehandleiding](https://tailscale.com/download/linux), meld deze computer en je browserapparaat aan bij je eigen tailnet, en activeer de vereiste MagicDNS/HTTPS-opties indien Tailscale daarom vraagt. Beperk toegang tot je eigen apparaten via tailnetbeleid.

De actuele, alleen-lezen gecontroleerde Serve-configuratie op deze computer is:

```text
https://robert-pc.tail8c36bd.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8788
```

Controleer en stel indien nodig de root-proxy opnieuw in:

```bash
tailscale serve status
sudo tailscale serve --bg --https=443 http://127.0.0.1:8788
tailscale serve status
```

Deze instelopdracht wijzigt de root-route op HTTPS-poort 443; controleer eerst of daar geen andere dienst staat. Een algemene `serve reset` is niet nodig. Gebruik **geen Funnel**, publieke port-forwarding of publieke reverse proxy. Serve blijft in de achtergrond actief; de Python-portal moet apart draaien. Op een nieuwe computer gebruik je diens werkelijke `.ts.net`-origin in zowel MCP-profiel als portal. Zie de [Serve-documentatie](https://tailscale.com/docs/reference/tailscale-cli/serve).

## 5. OpenAI Tunnel installeren en configureren

Download de geschikte Linux-release via de [officiële Secure MCP Tunnel-handleiding](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) en installeer `tunnel-client` op je PATH. Controleer:

```bash
tunnel-client --version
tunnel-client help quickstart
tunnel-client init --help
```

De lokaal gecontroleerde versie is 0.0.19; downloadlinks en installatiepakketten worden upstream beheerd. Maak/hergebruik in Platform een private tunnel voor één eigenaar. Koppel de juiste Platform-organisatie én ChatGPT-workspace. Aanmaken/wijzigen vereist Tunnels Read + Manage; runtime-key en pluginoperator vereisen Read + Use. Geef de runtime-key alleen de benodigde rechten. Account- en workspacebeschikbaarheid kunnen verschillen.

Voor een nieuw profiel op de bestaande host (niet over een werkend profiel schrijven):

```bash
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile garmin-plus \
  --tunnel-id tunnel_6ae7a0e2af9c8191aeafabc40bcc648d \
  --mcp-command "/home/robert/Documents-Prive/Projects/garmin-connector/.venv/bin/python /home/robert/Documents-Prive/Projects/garmin-connector/scripts/run_mcp.py --approval-mode browser --approval-origin https://robert-pc.tail8c36bd.ts.net --enable-uploads --enable-scheduling"
```

Pas de absolute paden en origin aan op een nieuwe host. Het standaard profielpad is `$XDG_CONFIG_HOME/tunnel-client` of `~/.config/tunnel-client`; bewaar alleen omgevingsreferenties voor geheimen, nooit de key zelf. De opdracht hierboven is een reproduceerbaar profielrecept; het huidige profielbestand en de accountrechten zijn in deze documentatieronde niet uitgelezen. Beide schrijfflags zijn opt-in en geven geen toestemming voor een Garmin-wijziging. Laat `--enable-scheduling` weg als je geen planning wilt.

Volg [STARTUP](STARTUP.md) om de key verborgen in te voeren, beide processen te starten en readiness te controleren. Met dezelfde omgevingsvariabelen kan de gebruiker aanvullend uitvoeren:

```bash
tunnel-client doctor --profile garmin-plus --explain
```

Doctor kan verbindingen controleren; deel geen ongeredigeerde diagnostiek. Zet geen raw HTTP-logging aan.

## 6. ChatGPT verbinden

Open in ChatGPT web Plugins → plus → Add custom MCP server → Connection: Tunnel. Selecteer dezelfde private tunnel en maak de plugin uitsluitend voor eigen gebruik beschikbaar, met passende tunneltoegangscontrole. Deze server biedt geen OAuth-endpoint. Vernieuw de tool-lijst en test eerst alleen `build_running_workout` met een korte training. Een geslaagde toolaanroep vanuit ChatGPT bevestigt de verbinding; readiness alleen volstaat niet. Laat de gebruiker daarna zelf een reviewverzoek beoordelen. Geen upload of planning als automatische installatietest. Zie [dagelijks gebruik](STARTUP.md) en de officiële OpenAI-handleiding hierboven.

## Opslag en git

`.gitignore` sluit `.venv/`, Python-caches, `.idea/` en exact `.env` uit. Het is **geen** algemene bescherming voor `.env.local`, losse keys, auth-JSON, sessies of tunnelprofielen. Houd die altijd op de [externe locaties](ARCHITECTURE.md#opslag-en-geheimen). Er zijn bij deze controle geen verdachte credentialbestandsnamen in de gevolgde bestanden gevonden; dat is geen volledige historische secret-scan. Controleer vóór commits `git status --short` en de staged diff lokaal, zonder gevoelige inhoud te delen. Voorbeelden van systemd-userdiensten bestaan in `examples/`; ze zijn niet automatisch geïnstalleerd. De tunneltemplate gebruikt nog profiel `garmin`: pas lokaal aan naar `garmin-plus`, inclusief organisatie en een mode-600 EnvironmentFile buiten de repo. Gebruik niet tegelijk systemd en de handmatige startprocedure.
