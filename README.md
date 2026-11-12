# Garmin Connector

Een private connector voor Garmin Connect via zes MCP-tools: hardloopactiviteiten lezen, gestructureerde trainingen bouwen, en na menselijke toestemming uploaden, inplannen of met één browsergoedkeuring beide uitvoeren. De Python-server gebruikt STDIO; ChatGPT bereikt hem via OpenAI Secure MCP Tunnel. Browsergoedkeuring loopt via private Tailscale HTTPS.

## Handleidingen

- [Installatie op een nieuwe Ubuntu-computer](docs/INSTALLATION.md)
- [Dagelijks opstarten en Garmin-workflow](docs/STARTUP.md)
- [Architectuur, beveiliging en gegevensopslag](docs/ARCHITECTURE.md)
- [Problemen oplossen en geheimen vervangen](docs/TROUBLESHOOTING.md)
- [Technische referentie: CLI, Inspector, payloadvoorbeelden en tests](docs/REFERENCE.md)
- [Private ChatGPT-integratie](docs/chatgpt-integration.md)

## Snel starten en stoppen op Ubuntu

Na de [eenmalige configuratie](docs/STARTUP.md):

```bash
./scripts/start-garmin.sh
./scripts/status-garmin.sh
./scripts/stop-garmin.sh
```

De scripts werken ook met een absoluut pad vanuit iedere directory. Start vraagt
zo nodig verborgen om de runtime-key. Ze gebruiken het bestaande profiel
`garmin-plus` en wijzigen geen Tailscale- of approvalconfiguratie. Lokale
readiness bevestigt geen ChatGPT-verbinding; test daarvoor de offline builder.

## Verificatiestatus

De eigenaar meldt een geslaagde handmatige verbinding met ChatGPT via de tunnel: activiteiten ophalen, een hardlooptraining maken, browsergoedkeuring en upload naar Garmin Connect. De configuratie staat in de installatiehandleiding. Deze documentatieronde herhaalt geen live Garmin-acties. Live kalenderplanning, geavanceerde HR/tijd/herhaalstructuren, mobiele ChatGPT-beschikbaarheid en horlogecompatibiliteit blijven onbevestigd.

Uploads en planning staan standaard uit. Inschakelflags staan alleen het aanvragen van toestemming toe. De gebruiker beoordeelt elke exacte actie; ChatGPT kan geen toestemming geven. De gecombineerde tool keurt expliciet upload én planning goed; losse tools houden eigen toestemming. Synchroniseren naar het horloge blijft een gebruikersactie. Geen publieke of gedeelde multi-userdienst.

## Ontwikkelen

Getest met Python 3.14.4; dependencies zijn vastgelegd in `requirements.txt`.

```bash
.venv/bin/python main.py preview
timeout 45s .venv/bin/python -m unittest discover -s tests -v
```

De preview is offline. Tests gebruiken mocks en tijdelijke goedkeuringsmappen; nooit live Garmin-uploads of planning. Zie [contributor instructions](AGENTS.md).

Voor “training klaarzetten voor een dag”: gebruik na serviceherstart en vernieuwde tooldiscovery bij voorkeur `upload_and_schedule_running_workout`. Pas `scheduled` voor de juiste datum rondt dit af; herinner daarna aan synchronisatie via Garmin Connect. Gecombineerde uitvoering is alleen offline/mock geverifieerd. [Workflow, hervatten en herstart](docs/STARTUP.md).
