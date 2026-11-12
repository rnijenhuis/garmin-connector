# Problemen oplossen

Begin met de [opstartprocedure](STARTUP.md). Deel nooit API-keys, wachtwoorden, Basic Authorization-headers, approval-ID's, volledige reviewlinks, sessiebestanden of ongeredigeerde logs. Schakel geen raw HTTP-logging of requestcapture in.

## Start-, stop- en statusscripts

Begin met `scripts/status-garmin.sh`: exitcode 1 betekent een vastgestelde lokale/transportfout; 2 betekent onvolledige verificatie. Geen van beide betekent automatisch een Garmin-fout. Ruwe proceslogs blijven uitgeschakeld. Alleen vaste diagnosecodes worden bewaard.

| Melding | Herstel |
|---|---|
| Ontbrekende afhankelijkheid / Python-omgeving | Controleer PATH voor `python3`, `tunnel-client`, `tailscale` en herstel de bestaande `.venv` volgens INSTALLATION. |
| API-key ontbreekt | Start in een interactieve terminal en voer de key verborgen in. In automatisering moet de runtime-omgeving hem al veilig aanbieden; geen argument of bestand in de repo. |
| Tailscale niet verbonden / Serve-route onjuist | Controleer `tailscale status` en `tailscale serve status`; herstel zelf volgens INSTALLATION. Scripts wijzigen geen route. Funnel wordt geweigerd. |
| Poort 8080 of 8788 bezet | Controleer of een handmatige of systemd-dienst draait. Stop die via diens eigen beheer; scripts nemen onbekende processen niet over. |
| Onderdeel direct gestopt / starttimeout | Controleer profiel, absolute launcher, browser-authbestand (mode 600), poorten en netwerk. Nieuw gestarte onderdelen worden opgeruimd, reeds beheerde diensten blijven staan. |
| Bestaande processen reageren niet | Controleer status, stop bewust met het stopscript en start opnieuw. Er is geen automatische retry. |
| STOPPED/UNMANAGED | Geen geldig eigen procesrecord: proces kan gecrasht zijn of buiten deze scripts draaien. Oude records verlenen geen stoprecht. |
| Onveilige runtime-directory | Controleer eigenaar en mode 700 van `~/.local/state/garmin-connector-runtime`; gebruik geen symlink of gedeelde map. |
| Proces stopt niet | Het record blijft behouden als zelfs SIGKILL niet tijdig voltooit; onderzoek lokaal, verwijder geen record om een procesidentiteit te omzeilen. |

## Wat de controles daadwerkelijk bewijzen

De gemelde storing is achteraf niet causaal bewezen: de oude scripts gooiden
procesuitvoer weg. Een herstart die helpt past bij een vastgelopen poller of
MCP-child, maar ook bij een tijdelijke netwerk- of control-plane-storing.
`/readyz` controleert startupgates, geen volledige ChatGPT-aanroep. Een root-404
controleert slechts een HTTP-respons, geen portal-login of upload.

De geïnstalleerde tunnel-client v0.0.19 beschrijft dit in
`tunnel-client help troubleshooting`. Het schema van `/health?details=true`
(schema_version 1) is offline gecontroleerd met een tijdelijke loopback-daemon,
fake key en mock control plane, zonder Garmin- of OpenAI-verkeer.
Zie ook de [officiële tunnelhandleiding](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

| Statuslaag | Bewijs en grens |
|---|---|
| Processen | Eigen PID, boot-ID, starttijd en commandhash. Geen netwerkbewijs. |
| Lokale HTTP | `/proc`-socket moet bij het beheerde proces horen. `/readyz` 200 is alleen `STARTUP_READY`; portalroot 404 alleen `EXPECTED_ROOT_404`. |
| Private HTTPS | Tailscale-daemon, verwachte Serve-configuratie zonder Funnel en TLS-rootrespons. Bewijst geen browserlogin. |
| Tunnel control plane | `RECENT_POLL_SUCCESS`: schema 1, snapshot maximaal 15 s oud, laatste succesvolle poll maximaal 90 s oud, polling/ok en nul opeenvolgende fouten. Bewijst recente control-plane-toegang, geen response-delivery of ChatGPT-workspacekoppeling. |
| Tunnelstoringen | `DISCONNECTED` bij pollfouten/backoff; `AUTH_FAILED` bij 401/403; `STALE` bij oude snapshot/succes; `UNKNOWN` bij ontbrekend/onbekend schema of ontbrekend bewijs. De vaste 90 s-grens veronderstelt de standaard 30 s long-poll; langere aangepaste polling kan conservatief STALE geven. |
| MCP discovery | `RECENT_DISCOVERY_OBSERVED` vereist recente initialize én complete tools/list in dezelfde healthsnapshot. Het is historisch bewijs; health-reads doen zelf geen MCP-probe. Anders UNVERIFIED/UNKNOWN. |
| Garmin-authenticatie | Status logt niet in en noemt deze UNVERIFIED. Een geslaagde `get_recent_activities(limit=1)` vanuit ChatGPT bewijst toegang op dat moment. Geen upload als loginprobe. |
| End-to-end MCP | Laat ChatGPT via de private plugin een `build_running_workout` bouwen, bijvoorbeeld één interval van 1000 m. Alleen een ontvangen correct resultaat verifieert die aanroep; het bewijst geen Garmin-write. Een los lokaal gestart MCP-proces test de tunnel niet. |

Onbekende/nieuwe healthschemas falen conservatief. Status print of bewaart geen
ruwe health-JSON, foutmeldingen of metadata uit het tunnelproces.
De statuscode blijft 2 als alle lokale controles en polling slagen: de scripts
kunnen de actuele ChatGPT-context en Garmin-toegang niet zelfstandig bewijzen.

## Veilige diagnosegeschiedenis en herstel

`scripts/status-garmin.sh --watch` observeert iedere 30 seconden en bewaart
pollstatuscodes. Stop met Ctrl-C. Deze observer draait op de voorgrond, start of
stopt geen diensten en houdt de lifecycle-lock niet vast. Zonder observer of
statusaanroep is er geen continue tunnelgeschiedenis; fouten tussen twee
metingen kunnen worden gemist.

De startscripts zetten `GARMIN_DIAGNOSTICS=1` voor portal en MCP-child. Bij een
andere launcher kan de eigenaar dit expliciet instellen. Herstart reeds draaiende
diensten bewust om nieuwe code en deze instelling te laden. De vaste records
staan in `~/.local/state/garmin-connector-runtime/diagnostics.jsonl` (directory
700, bestand 600, ongeveer 1 MiB begrensd; bij overschrijding wordt de historie
leeggemaakt). Ze bevatten uitsluitend Unix-tijd, PID, operation en outcome uit
vaste lijsten: onder meer authentication_required, authentication_failed,
approval_error/approval_required, upload_outcome_unknown en pollstatus.
Geen keys, tokens, wachtwoorden, approval-ID/hash/CSRF, URLs, namen, payloads,
activiteitsgegevens of exceptionteksten. Normale browser-authchallenges worden
niet als fout gelogd; onjuiste aangeleverde credentials wel. Diagnose-I/O-fouten
veranderen toolresultaten of toestemming niet. Geen toegang tot browserreview
als agent en geen raw HTTP/capture inschakelen.

Een vastgelopen verbinding herstelt mogelijk door de ingebouwde pollbackoff;
het geïnstalleerde clientprogramma ondersteunt ook interne STDIO-child-restart
(`--mcp.stdio-failure-policy`, standaard restart). De lokale mocktest bevestigde
pollbackoff, geen live herstel. Er is bewust geen extra automatische watchdog:
een herstart kan een lopende upload onderbreken en het resultaat onzeker maken.
De systemd-template herstart alleen na procesfalen, detecteert geen live hang.

Bij STALE/DISCONNECTED: observeer meerdere metingen en controleer netwerk/slaapstand.
Bij AUTH_FAILED: controleer runtime-key en organisatie privé, geen Garmin-loginreset
als oplossing voor een OpenAI-401. Als transport recent is maar de offline builder
faalt: controleer MCP-discovery, pluginselectie, workspace en gekoppelde tunnel.
Als herstel nodig blijft: controleer eerst eventuele onzekere writes in Garmin
Connect, stop/start bewust en test vervolgens uitsluitend de offline builder en
een read. Dit is transportherstel, nooit een uploadretry. Herhaal nooit automatisch
een upload of planning, maak niet automatisch vervangende approvals en verwijder
geen attemptrecords. Originele expiry, payloadbinding en single-use blijven gelden.
Een nieuwe write vereist menselijke reconciliatie en geldige afzonderlijke consent.

## `401 mismatched_organization`

Waarschijnlijke oorzaak: de organisatie die de tunnel-client meestuurt past niet bij de runtime-key of tunnelcontext. Dit is een OpenAI-control-plane-fout, geen Garmin-loginfout. Controleer lokaal dat de key voor de bedoelde organisatie is uitgegeven en dat de tunnel daarmee verbonden is. Gebruik de juiste runtime-key; een organisatieheader verleent geen rechten.

```bash
export CONTROL_PLANE_ORGANIZATION_ID="org-9ENwHB5TGd84UsFzcKujMFas"
```

Herstart de client met die variabele in **dezelfde terminal**, volgens STARTUP. Controleer Read + Use en de juiste workspacekoppeling in Platform. De precieze foutcodes zijn bekende praktijkmeldingen; deze ronde heeft ze niet opgewekt of accountrechten geaudit.

## `401 tunnel_active_organization_required`

Controleer of `CONTROL_PLANE_ORGANIZATION_ID` in de clientomgeving staat en overeenkomt met de persoonlijke Platform-organisatie van de runtime-key en de tunnel. De geïnstalleerde client ondersteunt ook `--control-plane.organization-id`; de dagelijkse procedure gebruikt de omgevingsvariabele. Alleen exporteren in een andere terminal helpt niet. Voor systemd moet de organisatie in de private serviceomgeving staan. Controleer organisatie/workspace-associaties en tunnelrechten volgens de [officiële OpenAI-handleiding](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

## `403 Invalid origin`

De POST moet exact `Origin: https://robert-pc.tail8c36bd.ts.net` hebben. De oude policy `no-referrer` leidde bij de gemelde Chrome-test tot `Origin: null`; de code bevat nu `strict-origin-when-cross-origin`. Zie [de verklaring en regressietests](ARCHITECTURE.md#opgeloste-origin-null-fout).

Controleer dat portal en MCP-profiel dezelfde origin gebruiken, open de originele HTTPS-link via Tailscale en herlaad de pagina na een portalherstart of update. Controleer lokaal in browser DevTools de responsepolicy en alleen de Origin-waarde, zonder credentials/tokens te kopiëren. Een proxy mag die headers niet herschrijven. Voeg nooit `null` aan de allowlist toe, schakel CSRF niet uit en vervals geen POST om een echte review te voltooien.

## `Request unavailable, expired, changed or already reviewed`

HTTP 409 betekent dat de pending aanvraag niet meer geldig beschikbaar is: bijvoorbeeld verlopen, al beoordeeld, verkeerde operatie/state of gewijzigde payload. Tien minuten loopt vanaf aanvraag. Na succesvolle goedkeuring is een tweede bezoek aan dezelfde pagina dus ook niet meer geldig, terwijl de goedgekeurde actie nog eenmaal voltooid kan worden vóór expiry.

Ga bij een al goedgekeurde aanvraag terug naar ChatGPT en laat dezelfde argumenten met de oorspronkelijke ID gebruiken. Na portalherstart eerst een nog pending formulier herladen. Bij verlopen/geweigerde/verbruikte aanvragen geen automatische vervanging: controleer eventuele Garmin-uitkomst en vraag alleen bij een bewuste nieuwe actie nieuwe toestemming. Bewerk geen statebestanden om goedkeuring af te dwingen.

## Browser vraagt om gebruikersnaam en wachtwoord

Dit is de bedoelde onafhankelijke Basic-authenticatie over private HTTPS. Gebruik `owner` en het lokale, met `--setup` ingestelde approvalwachtwoord (minimaal twintig tekens). Het is geen Garmin- of OpenAI-wachtwoord. Controleer het exacte HTTPS-adres en certificaat voordat je invoert. Herhaald vragen kan een fout wachtwoord, gestript Authorization-header of de tijdelijke limiet na mislukte pogingen betekenen. Browser/passwordmanager kan credentials onthouden; iedere actie vereist nog een nieuwe expliciete klik.

## Tunnel gestart, maar ChatGPT kan geen MCP-tools bereiken

Controleer proces, profiel `garmin-plus`, absolute interpreter/launcher en bestaande `.venv`. De tunnel start het MCP-child; een los gestart serverproces wordt niet door de tunnel gebruikt. Controleer dat alle zes tools in de plugin staan en vernieuw de tool-lijst. Controleer de gekoppelde ChatGPT-workspace, de organisatie, Read + Use en of de plugin in de conversatie is geselecteerd.

```bash
curl -i http://127.0.0.1:8080/readyz
tunnel-client doctor --profile garmin-plus --explain
```

Doctor moet dezelfde key/organisatieomgeving hebben als de draaiende client en kan netwerkcontroles uitvoeren. HTTP 200 is slechts lokale readiness. Bevestig end-to-end met een offline builderaanroep vanuit ChatGPT. Start niet met live uploads als diagnose. Beveilig localhost-admin/healthpoorten; zet geen remote admin UI aan. Een stille los gestarte STDIO-server is normaal: hij wacht op protocolberichten. Tik geen credentials in die stream.

## Tailscale HTTPS niet bereikbaar

Controleer op beide apparaten Tailscale-login/netwerk, de juiste hostnaam, tailnettoegangsbeleid, MagicDNS en geldig HTTPS. Geen certificaatwaarschuwingen omzeilen. Controleer lokaal:

```bash
tailscale serve status
curl -i http://127.0.0.1:8788/
```

Een lokale 404 op `/` kan aantonen dat er een HTTP-server antwoordt; alleen `/review/...` zijn echte portalroutes en vereisen authenticatie. Connection refused wijst op een ontbrekende portal of verkeerde poort. Een HTTPS-root-404 is op zichzelf geen storing. De ingestelde Serve-proxy moet naar `http://127.0.0.1:8788` wijzen; herstel volgens INSTALLATION, zonder andere routes blind te resetten. Open geen publieke poort en gebruik geen Funnel. Een onbereikbare portal bewijst geen tunnelstoring: het zijn twee verbindingen.

## Training goedgekeurd, maar nog niet geüpload

De portal verleent alleen toestemming en roept Garmin nooit aan. Ga terug naar ChatGPT: “Ik heb de bestaande upload goedgekeurd; voltooi die met dezelfde training en de oorspronkelijke approval ID.” ChatGPT moet de oorspronkelijke payload bewaren, niet opnieuw bouwen of een nieuwe review aanvragen. Controleer de toolrespons `uploaded` met workout-ID en controleer Garmin Connect. Een klik of `approval_required` is geen uploadbewijs.

## Overige veilige herstelacties

| Fout/status | Actie |
|---|---|
| `uploads_disabled` / `scheduling_disabled` | Controleer de afzonderlijke opt-inflags van het **tunnelprofiel**; herstart de betreffende client. Flags verlenen geen menselijke toestemming. |
| `authentication_required` | Vernieuw Garmin-sessie zelf in een privéterminal met `.venv/bin/python test_garmin.py`. Een verbruikte schrijftoestemming herleeft daardoor niet. |
| `invalid_input` | Controleer innerlijk workout-object, units, exclusieve eindcondities/doelen, limieten of positieve workout-ID en geldige `YYYY-MM-DD`. Zie REFERENCE. |
| `upload_outcome_unknown` / `schedule_outcome_unknown` | Eerst Garmin Connect controleren; mogelijk is de wijziging al uitgevoerd. Geen automatische retry of rollbackclaim. |
| `schedule_check_failed` | Geen POST bij mislukte controle/onbekend kalenderformaat. Laat de oorzaak onderzoeken; geen controle omzeilen. |
| `schedule_attempt_exists` | Duurzaam ID/datumrecord blokkeert herhaling, ook tussen goedkeuringsmodi. Alleen menselijke reconciliatie; agents verwijderen geen attempts. |
| `already_scheduled` | Bestaande passende kalenderentry gevonden; controleer in Garmin Connect, geen nieuwe POST nodig. |

## Geheimen vervangen

### OpenAI runtime-key

Maak als eigenaar een nieuwe restricted key met de juiste organisatierechten (Tunnels Read + Use). Stop de tunnel, voer de nieuwe key verborgen in volgens STARTUP en start opnieuw. Test eerst een offline ChatGPT-builderaanroep. Trek de oude key daarna in Platform in; bij vermoedelijke blootstelling onmiddellijk intrekken. Verwijder oude waarden uit private serviceomgeving/passwordmanager waar van toepassing. `unset CONTROL_PLANE_API_KEY` verwijdert alleen de shellwaarde, geen bestaande procesomgeving of server-side key. Bewaar geen keys in profiel-JSON/YAML, command arguments, repo of logs.

### Browserwachtwoord

Stop eerst de portal. De setup weigert terecht overschrijven. Stel als mens een vervangende hash op een nieuw extern bestand in:

```bash
.venv/bin/python -m garmin_connector.browser_approval \
  --setup --auth-file ~/.config/garmin-connector/browser-auth.next.json
```

Gebruik een nieuw uniek wachtwoord van minstens twintig tekens. Vervang na succesvolle setup zelf het bestand en start de normale portal opnieuw:

```bash
mv ~/.config/garmin-connector/browser-auth.next.json ~/.config/garmin-connector/browser-auth.json
chmod 600 ~/.config/garmin-connector/browser-auth.json
```

Het `.next`-bestand moet vooraf nog niet bestaan. De oude hash wordt hiermee vervangen; bewaar hem niet in de repo. Verwijder het oude wachtwoord uit browser/passwordmanager en meld met het nieuwe aan. Herstart invalideert open CSRF-formulieren, maar trekt reeds verleende bestandsgoedkeuringen niet in: die vervallen op hun oorspronkelijke deadline. Laat bij incidenten ook MCP/tunnel stoppen totdat open toestemmingen verlopen zijn. Verander geen approvals om consent te fabriceren en verwijder geen planningattempts.

### Garmin-sessie

Verander bij een incident het Garmin-wachtwoord en trek waar mogelijk oude sessies in via Garmin-accountbeheer. Maak daarna zelf een verse sessie met `test_garmin.py`; beheer eventuele oude lokale tokens alleen privé buiten de repository. Plak geen sessie-inhoud in diagnostiek. De exacte intrekkingsmogelijkheden hangen af van Garmin-accountbeheer.

## Gecombineerde actie

`uploaded_not_scheduled` bevat het opgeslagen workout-ID en de datum. Hervat bewust binnen de oorspronkelijke expiry met dezelfde argumenten/ID; na expiry is nieuwe browserreview voor identieke inputs nodig. Onzekere uploads worden nooit opnieuw geüpload. Na een onzekere planning controleert hervatten alleen de kalender. Verwijder nooit state om opnieuw te proberen. Zie [STARTUP](STARTUP.md#hervatten-en-gedeeltelijke-fouten).
