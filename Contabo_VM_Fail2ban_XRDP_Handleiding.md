Zeker! Hieronder staan de extra commando's voor je Markdown-handleiding. Hiermee kun je precies zien hoeveel mislukte inlogpogingen er zijn geweest, welke IP-adressen het actiefst zijn en hoeveel blokkeringen Fail2ban uitvoert.

## SSH- en XRDP-inlogpogingen analyseren

### 1. Totaal aantal mislukte SSH-inlogpogingen

```
sudo journalctl -u ssh --since "30 days ago" --no-pager |
grep -c "Failed password"
```

Dit toont het totale aantal mislukte SSH-wachtwoordpogingen in de beschikbare logs van de afgelopen 30 dagen.

### 2. Top 20 aanvallende IP-adressen

```
sudo journalctl -u ssh --since "30 days ago" --no-pager |
grep "Failed password" |
grep -oP 'from \K[0-9.]+' |
sort | uniq -c | sort -nr | head -20
```

Dit geeft een overzicht van de IP-adressen met de meeste mislukte pogingen.

### 3. Aantal mislukte SSH-pogingen per dag

```
sudo journalctl -u ssh --since "30 days ago" \
--no-pager --output=short-iso |
grep "Failed password" |
cut -d'T' -f1 |
sort | uniq -c
```

Hiermee ontdek je op welke dagen de meeste pogingen plaatsvinden.

### 4. Aantal mislukte SSH-pogingen per uur

```
sudo journalctl -u ssh --since "24 hours ago" \
--no-pager --output=short-iso |
grep "Failed password" |
cut -c1-13 |
sort | uniq -c
```

Hiermee zie je op welke uren de meeste aanvallen plaatsvinden.

### 5. Totaal aantal mislukte XRDP-logins

```
sudo grep -c 'AUTHFAIL:' /var/log/xrdp-sesman.log
```

Dit telt de mislukte RDP-aanmeldingen in het huidige XRDP-sesman-logbestand.

### 6. Aantal XRDP-logins per IP-adres

```
sudo grep 'AUTHFAIL:' /var/log/xrdp-sesman.log |
grep -oP 'ip=::ffff:\K[0-9.]+' |
sort | uniq -c | sort -nr
```

### 7. Hoeveel IP-adressen heeft Fail2ban geblokkeerd?

```
for jail in sshd xrdp; do
  echo "===== $jail ====="
  sudo fail2ban-client status "$jail" |
  grep -E 'Currently failed|Total failed|Currently banned|Total banned|Banned IP list'
done
```

Hierbij betekent `Currently banned` het aantal actieve blokkeringen en `Total banned` het aantal blokkeringen sinds de jail is gestart. Dit laatste is niet noodzakelijk het aantal unieke IP-adressen.

### 8. Live het aantal blokkeringen volgen

```
watch -n 10 'sudo fail2ban-client status sshd; sudo fail2ban-client status xrdp'
```

Vernieuwt elke 10 seconden. Stoppen met `Ctrl+C`.

Dit is het commando dat precies die logregels toont, inclusief datum, tijd, gebruikersnaam en IP-adres:

```
sudo journalctl -u ssh --since "24 hours ago" --no-pager | grep "Failed password"
```

Wil je live meekijken terwijl nieuwe inlogpogingen binnenkomen?

```
sudo journalctl -u ssh -f | grep --line-buffered "Failed password"
```

Dit toont direct nieuwe mislukte SSH-inlogpogingen. Stoppen doe je met `Ctrl+C`.

Wil je alleen de laatste 20 pogingen zien?

```
sudo journalctl -u ssh --no-pager | grep "Failed password" | tail -20
```





# Contabo Ubuntu-VM — SSH, XRDP en Fail2ban

> **Praktische beheerhandleiding**
> Omgeving: Contabo VPS/VDS · Ubuntu 24.04 · XFCE · xrdp 0.9.24 · Fail2ban met `nftables`
> Laatst bijgewerkt: 14 oktober 2026

## 1. Snel overzicht

Op deze VM zijn twee Fail2ban-jails actief:

| Jail | Doel | Poort | Ingestelde regel |
|---|---|---:|---|
| `sshd` | SSH-beveiliging | 22/TCP | 5 mislukte pogingen binnen 10 minuten → 24 uur ban |
| `xrdp` | Remote Desktop-beveiliging | 3389/TCP | 5 mislukte pogingen binnen 10 minuten → 1 uur ban |

**Let op:** Fail2ban blokkeert herhaalde mislukte inlogpogingen, maar schermt de poorten niet volledig af. SSH en RDP zijn voorlopig rechtstreeks via het publieke IP bereikbaar. De structurele vervolgstap is Tailscale testen en daarna de publieke toegang beperken via de Contabo-firewall.

## 2. Dagelijkse controle

### Beide jails en hun status

```bash
sudo fail2ban-client status
sudo fail2ban-client status sshd
sudo fail2ban-client status xrdp
```

### Compact overzicht van blokkeringen

```bash
for jail in sshd xrdp; do
    echo "===== $jail ====="
    sudo fail2ban-client status "$jail" | grep -E 'Currently failed|Total failed|Currently banned|Total banned|Banned IP list'
done
```

### Live volgen, elke 10 seconden

```bash
sudo watch -n 10 'fail2ban-client status sshd; echo; fail2ban-client status xrdp'
```

Stop met **Ctrl+C**.

### Wat betekenen de tellers?

| Veld | Uitleg |
|---|---|
| `Currently failed` | Mislukte pogingen die de jail momenteel binnen zijn detectievenster bijhoudt; dit is **niet** het aantal aanvallende IP's. |
| `Total failed` | Totaal door deze jail gematchte mislukte pogingen sinds de teller is gestart/gereset. |
| `Currently banned` | IP-adressen die op dit moment door deze jail geblokkeerd zijn. |
| `Total banned` | Aantal ban-acties sinds de teller is gestart/gereset; **niet per se unieke IP's**. |
| `Banned IP list` | IP-adressen die op dit moment geblokkeerd zijn. |

**Voorbeeld uit de VM:** `Currently banned: 4`, `Total banned: 8` betekent vier actieve bans en acht ban-acties in totaal. De overige vier zijn niet meer actief; dat kan komen door verlopen bans, handmatig deblokkeren of andere herinitialisatie van status.

## 3. Logs en mislukte inlogpogingen

### Recente mislukte SSH-logins

```bash
sudo journalctl -u ssh --since '24 hours ago' --no-pager | grep 'Failed password' | tail -30
```

### Meest actieve SSH-bron-IP's (laatste 30 dagen, voor zover logs bewaard zijn)

```bash
sudo journalctl -u ssh --since '30 days ago' --no-pager \
  | grep 'Failed password' \
  | grep -oP 'from \K[0-9.]+' \
  | sort | uniq -c | sort -nr | head -20
```

Deze lijst telt alleen **IPv4-adressen in regels met `Failed password`**. Historische SSH-pogingen zijn niet hetzelfde als de aantallen in Fail2ban.

### Succesvolle SSH-authenticaties

```bash
sudo journalctl -u ssh --since '30 days ago' --no-pager | grep 'Accepted '
```

Als je normaal via Windows Remote Desktop inlogt, hoeft hier geen succesvolle SSH-login te staan.

### Mislukte XRDP-logins

```bash
sudo grep 'AUTHFAIL:' /var/log/xrdp-sesman.log | tail -30
```

### Succesvolle of aangemaakte XRDP-sessies

```bash
sudo journalctl -u xrdp-sesman --since '7 days ago' --no-pager \
  | grep -E 'created session|reconnected session|Session started successfully'
```

Een aangemaakte sessie is een nuttig signaal, maar bewijst niet op zichzelf dat de volledige grafische login goed is verlopen.

### Fail2ban-logregels

```bash
sudo journalctl -u fail2ban --since '24 hours ago' --no-pager | tail -50
sudo grep -E 'Ban |Unban ' /var/log/fail2ban.log | tail -30
```

Als `/var/log/fail2ban.log` niet bestaat, gebruik de `journalctl`-variant.

## 4. Configuratie en werking controleren

### Fail2ban draait?

```bash
systemctl is-active fail2ban
sudo fail2ban-client status
```

### Configuratie controleren (geen wijzigingen)

```bash
sudo fail2ban-client -t
```

### Instellingen van beide jails opvragen

```bash
for jail in sshd xrdp; do
    echo "===== $jail ====="
    sudo fail2ban-client get "$jail" maxretry
    sudo fail2ban-client get "$jail" findtime
    sudo fail2ban-client get "$jail" bantime
    sudo fail2ban-client get "$jail" actions
done
```

`findtime` en `bantime` kunnen in seconden worden weergegeven.

### Gebruikte configuratiebestanden

```bash
sudo cat /etc/fail2ban/jail.d/sshd.local
sudo cat /etc/fail2ban/jail.d/xrdp.local
sudo cat /etc/fail2ban/filter.d/xrdp-auth.conf
```

De XRDP-filter herkent specifiek regels met `AUTHFAIL:`; gewone TLS- of scanmeldingen horen geen wachtwoordban te veroorzaken.

### Firewallactie controleren

```bash
sudo fail2ban-client get xrdp actions
sudo nft list ruleset | grep -i -C 3 f2b
```

In deze VM gebruikt Fail2ban `nftables`. Dat Fail2ban `nftables` gebruikt, betekent **niet** dat UFW actief is.

## 5. Een IP-adres handmatig beheren

**Alleen doen als je zeker weet waarom je dit wilt.** Controleer bij voorkeur via de Contabo-webconsole als je bang bent jezelf buiten te sluiten.

### Controleren of een IP in een jail geblokkeerd is

```bash
sudo fail2ban-client status sshd
sudo fail2ban-client status xrdp
```

### Een IP deblokkeren

```bash
sudo fail2ban-client set sshd unbanip 203.0.113.10
# Of voor RDP:
sudo fail2ban-client set xrdp unbanip 203.0.113.10
```

`203.0.113.10` is een **voorbeeldadres**. Vervang het door het juiste IP. Deblokkeer geen onbekende aanvallers zomaar.

### Een IP handmatig blokkeren

```bash
sudo fail2ban-client set sshd banip 203.0.113.10
# Of voor RDP:
sudo fail2ban-client set xrdp banip 203.0.113.10
```

**Nooit je eigen huidige publieke IP blokkeren.**

## 6. XRDP-vensters verdwijnen na enkele dagen

Eerder is vastgesteld dat een normale disconnect/reconnect op dezelfde display (`:10`) werkt. In de oudere logs zijn **XRDP-herstarts tijdens automatische Ubuntu-updates** zichtbaar. Dat is een sterke aanwijzing, maar de oorzaak is nog niet volledig bewezen.

### Actuele grafische sessie

```bash
echo "DISPLAY=$DISPLAY"
ps -eo pid,ppid,user,lstart,args | grep -E '[X]org|[x]rdp-sesman|[x]fce4-session'
```

### XRDP-herstarts bekijken

```bash
sudo journalctl -u xrdp -u xrdp-sesman --since '7 days ago' --no-pager \
  | grep -Ei 'Stopping|Starting|reconnected session|created session|failed' | tail -70
```

### Status services

```bash
systemctl is-active xrdp xrdp-sesman
systemctl show xrdp-sesman -p ActiveEnterTimestamp -p NRestarts
```

### De ingestelde `needrestart`-uitzondering

```bash
sudo cat /etc/needrestart/conf.d/99-xrdp.conf
```

Verwachte inhoud:

```perl
$nrconf{override_rc}{qr(^xrdp(-sesman)?[.]service$)} = 0;
```

Dit is bedoeld om automatische herstarts van XRDP door `needrestart` te voorkomen. Het beschermt niet tegen **alle** mogelijke serviceherstarts. We beoordelen de werking pas definitief na toekomstige updates.

**Niet zomaar uitvoeren:** `sudo systemctl restart xrdp`, `sudo systemctl restart xrdp-sesman`, `pkill Xorg` of een reboot terwijl de grafische sessie en jobs draaien.

## 7. Netwerkbeveiliging

### Controleren welke poorten luisteren

```bash
sudo ss -tlnp | grep -E ':(22|3389)\b'
```

### UFW-status bekijken

```bash
sudo ufw status verbose
```

De laatst gemeten status was `inactive`. Luisteren op `0.0.0.0` of `[::]` betekent dat een dienst op alle interfaces luistert; de daadwerkelijke bereikbaarheid wordt ook bepaald door externe firewalls.

**Belangrijk:** de VM heeft veel ongewenste SSH- en RDP-verbindingspogingen ontvangen. Fail2ban is een tussenmaatregel. De aanbevolen structurele route:

1. Tailscale installeren op Ubuntu én Windows.
2. Nieuwe RDP-verbinding testen via het Tailscale-IP.
3. Controleren of ook SSH werkt via Tailscale en of er andere noodzakelijke inkomende diensten zijn.
4. Pas daarna publieke poorten 22 en 3389 beperken in de Contabo-firewall.

Schakel niet blind `ufw enable` in en blokkeer geen poorten voordat een alternatieve werkende toegang is getest.

## 8. Snelle probleemoplossing

| Situatie | Eerst controleren |
|---|---|
| Verdacht veel SSH-pogingen | `sudo fail2ban-client status sshd` |
| Mislukte RDP-logins | `sudo fail2ban-client status xrdp` en `AUTHFAIL`-log |
| Fail2ban-configuratie gewijzigd | `sudo fail2ban-client -t` en dan pas gecontroleerd reloaden |
| Desktopvensters verdwenen | `echo "$DISPLAY"` en XRDP-sessielogs, **geen processen killen** |
| Niet meer via RDP bereikbaar | Eerst Contabo-console, netwerkregels, eigen ban-IP en XRDP-status controleren |
| IP blijft terugkomen | Publieke toegang beperken; niet eindeloos losse IP's handmatig blokkeren |

---

*Deze handleiding is afgestemd op de getoonde configuratie en logs van oktober 2026. Opgenomen historische aantallen zijn momentopnamen; actuele waarden kun je opvragen met de commando's hierboven.*
