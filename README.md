# Garmin Connector

Een private connector voor Garmin Connect via vijf MCP-tools: hardloopactiviteiten lezen, gestructureerde trainingen bouwen, en na afzonderlijke menselijke toestemming uploaden of inplannen. De Python-server gebruikt STDIO; ChatGPT bereikt hem via OpenAI Secure MCP Tunnel. Browsergoedkeuring loopt via private Tailscale HTTPS.

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

Uploads en planning staan standaard uit. Inschakelflags staan alleen het aanvragen van toestemming toe. De gebruiker beoordeelt elke exacte actie; ChatGPT kan geen toestemming geven. Uploaden, inplannen en synchroniseren naar een horloge zijn afzonderlijke stappen. Geen publieke of gedeelde multi-userdienst.

## Ontwikkelen

Getest met Python 3.14.4; dependencies zijn vastgelegd in `requirements.txt`.

```bash
.venv/bin/python main.py preview
timeout 45s .venv/bin/python -m unittest discover -s tests -v
```

De preview is offline. Tests gebruiken mocks en tijdelijke goedkeuringsmappen; nooit live Garmin-uploads of planning. Zie [contributor instructions](AGENTS.md).
