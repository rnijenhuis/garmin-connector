# Dagelijks opstarten en gebruiken

Eenmalige voorbereiding: [INSTALLATION](INSTALLATION.md). De computer moet aan en wakker blijven, met uitgaand HTTPS naar OpenAI en Garmin. Tailscale moet werken op deze computer en op het apparaat dat de reviewpagina opent.

## Eenmalig instellen

Voltooi eerst INSTALLATION, inclusief het bestaande profiel `garmin-plus`, de
browserwachtwoordconfiguratie en de private Tailscale Serve-route. Deze scripts
maken geen tunnel aan en wijzigen Serve, wachtwoord of approvals niet. Gebruik
ze niet tegelijk met de systemd-voorbeelden of handmatig gestarte diensten.

Vereist: Ubuntu/Linux met pidfds, Bash, systeem-Python 3.9+ (het project zelf
gebruikt zijn bestaande `.venv`), `tunnel-client` en `tailscale` op PATH.

```bash
cd ~/Documents-Prive/Projects/garmin-connector
chmod 700 scripts/{start,stop,status}-garmin.sh
```

## Starten, stoppen en status

De absolute paden werken vanuit iedere directory:

```bash
~/Documents-Prive/Projects/garmin-connector/scripts/start-garmin.sh
~/Documents-Prive/Projects/garmin-connector/scripts/status-garmin.sh
~/Documents-Prive/Projects/garmin-connector/scripts/stop-garmin.sh
```

Start vraagt de OpenAI runtime-key verborgen in een interactieve terminal als
`CONTROL_PLANE_API_KEY` (of als fallback `OPENAI_API_KEY`) ontbreekt. Voer de
key nooit als commandargument in. De vaste organisatie is
`org-9ENwHB5TGd84UsFzcKujMFas`. Alleen het tunnelproces ontvangt de runtime-key;
de portal ontvangt beide keyvariabelen niet. `scripts/run_mcp.py` verwijdert ze
ook voordat Garmin-code wordt geladen.

Het achtergrondproces erft een eigen omgevingskopie, zodat de sleutel na het
sluiten van het startscript beschikbaar blijft. De scripts schrijven die nooit
naar schijf, printen hem niet en bewaren geen proceslogs. Procesuitvoer wordt
weggegooid. De key blijft in procesgeheugen/omgeving: root en processen met
voldoende rechten binnen hetzelfde gebruikersaccount kunnen die mogelijk lezen.
Gebruik daarom alleen het eigen, vertrouwde account. Geen automatische herstart
na een crash of reboot; start dan bewust opnieuw en voer zo nodig de key in.

PID-records (PID, boot-ID, starttijd en commandhash) en een gedeelde flock staan
in `~/.local/state/garmin-connector-runtime`, directory 700, bestanden 600.
Stop controleert de identiteit en gebruikt pidfds tegen PID-hergebruik. Eerst
SIGTERM, na vijf seconden zo nodig SIGKILL. Onbekende of oude PID-records geven
geen recht om een ander proces te stoppen. Alleen beheerde hoofdprocessen worden
gestopt; het tunnelprogramma is verantwoordelijk voor zijn eigen MCP-child.
Tailscale zelf en Serve blijven actief. Een bezette poort wordt nooit overgenomen.

Start wacht op readiness en minimaal twee seconden stabiele processen (maximaal
vijftien seconden plus begrensde netwerkcontroles). Dit voorkomt succes bij
gebruikelijke directe crashes, maar kan een latere crash niet uitsluiten.
Bij een mislukte start worden alleen nieuw gestarte processen teruggedraaid.
Gelijktijdige opdrachten wachten op dezelfde vergrendeling.

## Gereedheid controleren

Status toont afzonderlijk beheerde processen, Tailscale, HTTP 200 op
`http://127.0.0.1:8080/readyz`, de lokale portal en private HTTPS-route.
De portal heeft geen homepage: HTTP 404 op `/` is hier de verwachte respons;
het bewijst bereikbaarheid, geen geslaagde login of review. TLS-validatie blijft
aan, redirects worden niet gevolgd en er worden geen credentials meegestuurd.
Serve moet HTTPS op 443 naar `http://127.0.0.1:8788` routeren zonder Funnel.
Onbekende JSON-configuratie wordt geweigerd. Exitstatus 0 betekent alle lokale
controles geslaagd, 1 betekent fout of onvolledige status.

Een draaiend proces of HTTP 200 bewijst geen OpenAI- of ChatGPT-verbinding.
Test die zelf met een offline `build_running_workout` vanuit de private
ChatGPT-plugin. Geen upload of planning als verbindingstest. Accountrechten,
workspacekoppeling en mobiele beschikbaarheid worden niet door de scripts
geverifieerd. Zie ook de [officiële tunnelhandleiding](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

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

## Veilig een nieuwe API-key gebruiken

Stop eerst met `scripts/stop-garmin.sh`. Verwijder eventuele oude shellwaarden:

```bash
unset CONTROL_PLANE_API_KEY OPENAI_API_KEY
~/Documents-Prive/Projects/garmin-connector/scripts/start-garmin.sh
```

Voer de nieuwe restricted runtime-key in de verborgen prompt in. Test de offline
ChatGPT-builder en trek de oude key in Platform in. Bij vermoedelijke blootstelling
meteen intrekken. `unset` verandert geen al draaiende procesomgeving en trekt
geen key in. Bewaar niets in shellprofielen, commandarguments, repo of logs.
Zie [credentialrotatie](TROUBLESHOOTING.md#geheimen-vervangen).
Terminal/Inspector blijft beschikbaar in de [technische referentie](REFERENCE.md).
