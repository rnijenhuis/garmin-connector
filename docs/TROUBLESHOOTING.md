# Problemen oplossen

Begin met de [opstartprocedure](STARTUP.md). Deel nooit API-keys, wachtwoorden, Basic Authorization-headers, approval-ID's, volledige reviewlinks, sessiebestanden of ongeredigeerde logs. Schakel geen raw HTTP-logging of requestcapture in.

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

Controleer proces, profiel `garmin-plus`, absolute interpreter/launcher en bestaande `.venv`. De tunnel start het MCP-child; een los gestart serverproces wordt niet door de tunnel gebruikt. Controleer dat alle vijf tools in de plugin staan en vernieuw de tool-lijst. Controleer de gekoppelde ChatGPT-workspace, de organisatie, Read + Use en of de plugin in de conversatie is geselecteerd.

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
