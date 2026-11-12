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
naar schijf, printen hem niet en bewaren geen ruwe proceslogs. Alleen vaste diagnosecodes worden bewaard (zie TROUBLESHOOTING). Procesuitvoer wordt
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

Status toont afzonderlijk beheerde processen, Tailscale, recente control-plane polling, historische MCP-discovery, onbevestigde Garmin-authenticatie en end-to-end MCP, HTTP 200 op
`http://127.0.0.1:8080/readyz`, de lokale portal en private HTTPS-route.
De portal heeft geen homepage: HTTP 404 op `/` is hier de verwachte respons;
het bewijst bereikbaarheid, geen geslaagde login of review. TLS-validatie blijft
aan, redirects worden niet gevolgd en er worden geen credentials meegestuurd.
Serve moet HTTPS op 443 naar `http://127.0.0.1:8788` routeren zonder Funnel.
Onbekende JSON-configuratie wordt geweigerd. Exitstatus 1 betekent een aangetoonde lokale/transportfout; 2 betekent onvolledige verificatie, ook als alle lokale controles slagen. Er wordt geen algemeen groen resultaat afgegeven zonder end-to-end bewijs.

Een draaiend proces of HTTP 200 bewijst geen OpenAI- of ChatGPT-verbinding.
Test die zelf met een offline `build_running_workout` vanuit de private
ChatGPT-plugin. Geen upload of planning als verbindingstest. Accountrechten,
workspacekoppeling en mobiele beschikbaarheid worden niet door de scripts
geverifieerd. Zie ook de [officiële tunnelhandleiding](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

## Volledige Garmin-workflow

1. Vraag ChatGPT om recente hardloopactiviteiten of details/laps op te halen. Dit gebruikt de opgeslagen Garmin-sessie en geeft alleen gefilterde trainingsgegevens terug.
2. Laat een gestructureerde hardlooptraining bouwen. Controleer naam, volgorde, afstand/tijdsduur en tempo- of hartslagdoelen. Dit bouwen is offline.
3. Voor **training klaarzetten voor een dag** gebruikt ChatGPT bij voorkeur `upload_and_schedule_running_workout` met de volledige innerlijke `workout` en een expliciete datum (`YYYY-MM-DD`, bepaald in `Europe/Amsterdam`). Gebruik deze actie pas nadat de services zijn herstart en de nieuwe tool daadwerkelijk in ChatGPT beschikbaar is.
4. Zonder `approval_id` maakt MCP uitsluitend een lokaal verzoek. De reviewlink toont naam, alle stappen/doelen, berekenbare totalen en datum. De pagina vraagt duidelijk toestemming voor **zowel uploaden als inplannen**.
5. Open de link zelf via private HTTPS, log in als `owner` en keur alleen goed als alles klopt. ChatGPT mag de pagina nooit voor je bedienen. Een chatbericht “ja” vervangt de browsergoedkeuring niet.
6. Ga terug naar ChatGPT en vraag door te gaan. ChatGPT gebruikt dezelfde gecombineerde tool met **identieke workout, datum en oorspronkelijke approval ID**.
7. De opdracht is pas afgerond bij **`status: scheduled` met de juiste datum en workout-ID**. `uploaded_not_scheduled` betekent dat de upload wel gelukt is, maar de planning nog niet bevestigd is. Zie hieronder voor hervatten; live gecombineerde planning is nog onbevestigd.
8. Synchroniseer daarna je horloge via Garmin Connect en stuur de training waar ondersteund naar het horloge. Controleer de training op het horloge. De connector bevestigt nooit dat hij op het horloge staat.

De bestaande losse upload- en planningtools blijven beschikbaar met elk eigen toestemming, ook in terminalmodus.

### Hervatten en gedeeltelijke fouten

Een operatiejournaal buiten de repository bewaart voortgang per exacte workout/datum/operatie, ook over herstarts en verschillende approval IDs. Een eenmaal gestarte upload wordt nooit herhaald. Het Garmin-workout-ID wordt direct na succesvolle upload opgeslagen. Bij fouten vóór een planning-POST kan de gebruiker expliciet laten hervatten: dezelfde argumenten en verbruikte approval ID blijven alleen tot de **oorspronkelijke** tienminutengrens geldig. Er wordt geen nieuwe upload gemaakt.

Na verlopen toestemming is nieuwe browsergoedkeuring nodig voor dezelfde workout/datum. Vraag deze bewust aan; ChatGPT maakt nooit automatisch een vervangend verzoek. De nieuwe toestemming gebruikt hetzelfde journaal en voert uitsluitend ontbrekend werk uit. Als een upload een onbekende response gaf of crashte voordat het ID veilig opgeslagen was, is de uitkomst onzeker en blijft opnieuw uploaden geblokkeerd, ook met nieuwe toestemming. Controleer Garmin Connect handmatig.

Een fout/onduidelijke response ná een planning-POST is eveneens onzeker. Expliciet hervatten controleert alleen de kalender: bij bevestiging volgt `scheduled`, anders blijft handmatige reconciliatie nodig. Er volgt nooit een tweede POST. Verwijder geen journaal of pogingrecords om deze beveiliging te omzeilen. Handmatige wijzigingen of andere Garmin-clients kunnen tussen kalendercontrole en POST racen; lokale locks voorkomen geen externe races.

### Services herstarten na deze update

Bij gebruik van de beheerscripts (niet combineren met systemd):

```bash
./scripts/stop-garmin.sh
./scripts/start-garmin.sh
./scripts/status-garmin.sh
```

Het bestaande tunnelprofiel moet `--approval-mode browser`, de private `--approval-origin`, `--enable-uploads` én `--enable-scheduling` bevatten. Het bestaande installatievoorbeeld bevat die al. Ververs daarna de tools in ChatGPT en controleer dat alle **zes** tools inclusief `upload_and_schedule_running_workout` zichtbaar zijn. Test de verbinding alleen met de offline builder. Een lokale wijziging of draaiende service bewijst nog geen bijgewerkte ChatGPT-toolset.

Als je bewust de systemd-voorbeelden gebruikt in plaats van scripts:

```bash
systemctl --user restart garmin-browser-approval.service garmin-tunnel.service
systemctl --user status garmin-browser-approval.service garmin-tunnel.service
```

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
