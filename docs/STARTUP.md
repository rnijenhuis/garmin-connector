# Dagelijks opstarten en gebruiken

Eenmalige voorbereiding: [INSTALLATION](INSTALLATION.md). De computer moet aan en wakker blijven, met uitgaand HTTPS naar OpenAI en Garmin. Tailscale moet werken op deze computer en op het apparaat dat de reviewpagina opent.

## Terminal 1 — OpenAI Tunnel

```bash
cd ~/Documents-Prive/Projects/garmin-connector

export CONTROL_PLANE_ORGANIZATION_ID="org-9ENwHB5TGd84UsFzcKujMFas"

read -r -s -p 'OpenAI API-key: ' CONTROL_PLANE_API_KEY
echo
export CONTROL_PLANE_API_KEY

tunnel-client run --profile garmin-plus
```

Voer de restricted runtime-key alleen lokaal in. De shellhistory bevat de leesopdracht, niet de ingevoerde key. Sluit deze terminal niet tijdens gebruik. Het profiel start zelf het Python MCP-childproces via `scripts/run_mcp.py`; een extra losse MCP-server is niet nodig. De launcher verwijdert `CONTROL_PLANE_API_KEY` en `OPENAI_API_KEY` voordat Garmin-code wordt geïmporteerd.

## Terminal 2 — Browser Approval Server

```bash
cd ~/Documents-Prive/Projects/garmin-connector

.venv/bin/python -m garmin_connector.browser_approval \
  --origin https://robert-pc.tail8c36bd.ts.net \
  --port 8788
```

Deze server bindt uitsluitend `127.0.0.1`. Gebruikersnaam is `owner`; gebruik het eerder met `--setup` ingestelde wachtwoord. Bij een bezette poort eerst nagaan of de bedoelde server al draait; start geen tweede instantie.

## Gereedheid controleren

Voer in een extra terminal uit:

```bash
tailscale serve status
curl -i http://127.0.0.1:8080/readyz
```

Serve moet de [vastgelegde route](INSTALLATION.md#4-tailscale-en-private-https) naar poort 8788 tonen. HTTP 200 van `/readyz` bevestigt alleen lokale tunnelgereedheid; het bewijst geen volledige ChatGPT → MCP → Garmin-verbinding en controleert de portal niet. Open in ChatGPT de private Garmin-plugin en laat een korte training offline bouwen. Controleer alleen bij een werkelijk aangevraagd reviewverzoek dat de HTTPS-pagina bereikbaar is; de root-URL van de portal heeft geen homepage en mag 404 geven.

## Volledige Garmin-workflow

1. Vraag ChatGPT om recente hardloopactiviteiten of details/laps op te halen. Dit gebruikt de opgeslagen Garmin-sessie en geeft alleen gefilterde trainingsgegevens terug.
2. Laat een gestructureerde hardlooptraining bouwen. Controleer naam, volgorde, afstand/tijdsduur en tempo- of hartslagdoelen. Dit bouwen is offline.
3. Vraag expliciet om upload naar Garmin Connect. ChatGPT gebruikt het innerlijke `workout`-object; je hoeft geen JSON te kopiëren.
4. MCP maakt een lokaal pending verzoek en retourneert een reviewlink naar de Browser Approval Server. Er is nog geen upload of authenticatie voor die schrijfactie.
5. Open de link zelf via Tailscale HTTPS, log in als `owner` en beoordeel de exacte actie, payload, SHA256 en vervaltijd. Klik alleen bij akkoord op de actiespecifieke goedkeuring. ChatGPT mag deze pagina nooit voor je bedienen.
6. Ga terug naar ChatGPT en zeg dat het mag doorgaan. ChatGPT roept dezelfde uploadtool aan met **identieke argumenten en de oorspronkelijke approval ID**. Pas nu wordt toestemming eenmaal verbruikt en de upload uitgevoerd. Controleer de status `uploaded`, workout-ID en naam; open Garmin Connect om de training te controleren.
7. Vraag desgewenst afzonderlijk om deze bestaande workout-ID op een concrete datum in te plannen. Controleer de datum in `Europe/Amsterdam` (exact `YYYY-MM-DD`). Hiervoor volgt een nieuwe, afzonderlijke browsergoedkeuring en daarna dezelfde planningaanroep met diens oorspronkelijke ID. Live planning blijft nog onbevestigd.
8. Open Garmin Connect, stuur de training waar ondersteund naar je horloge en synchroniseer. Controleer de training op het horloge. De connector doet geen device-push en kan niet bevestigen dat de training op het horloge staat.

Elke toestemming vervalt tien minuten na **aanvraag**, niet na de klik. De portal voert zelf geen Garmin-actie uit. ChatGPT native bevestigingen of onthouden toolrechten vervangen browsergoedkeuring niet. Geen automatisch nieuw verzoek, poll-loop of retry bij twijfel; controleer eerst Garmin Connect. Zie [fouten en herstel](TROUBLESHOOTING.md).

## Stoppen

Stop beide voorgrondprocessen met Ctrl+C. Verwijder in Terminal 1 daarna de runtime-key uit de shellomgeving:

```bash
unset CONTROL_PLANE_API_KEY
```

Dit trekt de key niet in. Tailscale Serve in achtergrond blijft geconfigureerd, maar kan zonder portal geen reviews bedienen. Voor key-intrekking en wachtwoordrotatie: [troubleshooting](TROUBLESHOOTING.md#geheimen-vervangen). Terminal/Inspector blijft als alternatieve lokale workflow beschikbaar in de [technische referentie](REFERENCE.md).
