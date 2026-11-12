# Private ChatGPT-integratie

De bestaande handleiding is ondergebracht in de onderstaande onderwerpen, zodat installatie, dagelijks gebruik en beveiliging elk één bron hebben. STDIO met Inspector en terminalgoedkeuring blijft ondersteund.

- [Installatie, werkende configuratie en accountkoppeling](INSTALLATION.md)
- [Opstarten, browserreview en Garmin-workflow](STARTUP.md)
- [Architectuur en vertrouwensgrenzen](ARCHITECTURE.md)
- [Problemen oplossen en credentialrotatie](TROUBLESHOOTING.md)
- [Technische CLI-/Inspectorreferentie en payloadvoorbeelden](REFERENCE.md)

De eigenaar heeft de ChatGPT-tunnelroute, activiteiten ophalen en browsergoedgekeurde upload handmatig succesvol getest. Deze documentatieronde herhaalt geen live writes. Kalenderplanning, mobiele ChatGPT-beschikbaarheid en geavanceerde Garmin-/deviceondersteuning blijven onbevestigd.

ChatGPT presenteert steeds samenvatting → reviewlink → wacht op gebruiker → dezelfde toolargumenten met oorspronkelijke approval ID. Geen handmatig JSON kopiëren, modelgoedkeuring of automatische schrijfretry. Voor een training op een dag gebruikt de bijgewerkte runtime bij voorkeur de gecombineerde tool met één expliciete browsergoedkeuring voor beide acties. Alleen `scheduled` voor de juiste datum betekent afgerond. De losse tools houden afzonderlijk consent; synchronisatie naar het horloge blijft een gebruikersactie. Deze integratie is uitsluitend voor één eigenaar, privé, zonder publieke OAuth-service of mapping van meerdere Garmin-gebruikers. Publiceer of deel de tunnel/plugin niet in een multi-userworkspace.

De gecombineerde operatie is offline/mock getest, niet live geverifieerd. Zie [STARTUP](STARTUP.md) voor herstart, tooldiscovery, hervatten en synchronisatie.
