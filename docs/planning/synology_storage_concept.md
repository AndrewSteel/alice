# Zusammenfassung -- Synology DS718+ als zentraler Linux-Dateispeicher

## 1. Zielarchitektur

- **DS718+** = zentraler Produktivspeicher
- **DS224+** = ausschließlich Backup
- Linux-Clients greifen per **NFSv4.1** auf die Daten zu.
- Keine Dateisynchronisation zwischen PCs mehr.
- Persönliche Daten und gemeinsame Daten werden getrennt.

------------------------------------------------------------------------

## 2. Hardware

- Synology DS718+
- 2 × NAS-Festplatten (8 TB)
- RAID: **SHR**
- Dateisystem: **Btrfs**

### Vorbereitung vor Inbetriebnahme (DS718+ ist ca. 9 Jahre alt)

Vor der Produktivnutzung prüfen:

- **SMART-Test** beider Festplatten durchführen (Langer Test, mind. 24 h) — **nur bei gebrauchten Platten nötig**; neue Platten können direkt eingesetzt werden
- **DSM-Version** prüfen: Synology listet DS718+ noch als unterstützt, aber Supportende beobachten
- **Lüfter und Gehäuse**: auf Verschleiß und ungewöhnliche Geräusche prüfen

------------------------------------------------------------------------

## 3. Freigaben

Jede unten genannte oberste Ebene ist eine **eigenständige DSM-Freigabe** (Shared Folder) — kein gemeinsamer Elternordner. Grund: Ohne Windows-ACL erben Unterordner nur die Rechte ihrer Freigabe; da einzelne Bereiche unterschiedliche Gruppenrechte brauchen, bekommt jeder Bereich mit eigenem Rechteprofil eine eigene Freigabe (siehe Abschnitt 4, "Gruppen").

### Persönliche Freigaben

Je eine Freigabe pro Benutzer, nur für diesen Benutzer zugänglich:

    user1/
        Documents
        Pictures
        Music
        Videos
        Projects
        SmartHome
        Finance
        Archive
        Desktop

    user2/
        ... (analog)

### Gemeinsame Freigaben

Je eine Freigabe pro Rechteprofil:

    Scanner/
    Family/
        Templates/
    Media/
        Music
        Videos
    Pictures/
    Public/
    AI/

> **Pictures separat von Media:** Synology Photos (für den Smartphone-Foto-Upload, siehe Abschnitt „Synology Photos") funktioniert nur mit einer eigenen Freigabe, keiner Unterordner-Bibliothek innerhalb einer anderen Freigabe. Deshalb `Pictures` als eigenständige Freigabe angelegt und die bisher unter `Media/Pictures` liegenden Fotos dorthin migriert — `Media` enthält seither nur noch `Music` und `Videos`.

------------------------------------------------------------------------

## 4. DSM-Konfiguration

### Benutzer

- normales Benutzerkonto `user1`
- separates Administratorkonto (z.B. `user1-admin`)
- Standardkonto `admin` deaktivieren

### Gruppen

Empfohlene Gruppen:

- family
- media
- scanner
- public
- backup

Gemeinsame Ordner erhalten Gruppenrechte statt Einzelrechte. Zuordnung Freigabe → Berechtigte:

| Freigabe | Berechtigt |
|---|---|
| `Scanner` | Gruppe `scanner` |
| `Family` (inkl. `Templates`) | Gruppe `family` |
| `Media` | Gruppe `media` |
| `Pictures` | einzelne Nutzer direkt freigegeben (kein Gruppen-Mapping — Synology Photos verwaltet den Zugriff pro Nutzer) |
| `Public` | Gruppe `public` (kann auch Gäste ohne Familienzugriff enthalten) |
| `AI` | nur `user1` |

------------------------------------------------------------------------

### Dateidienste

Aktivieren:

- NFSv4.1 (nicht NFSv4.0 — v4.1 hat bessere Performance und Fehlerbehandlung)
- SMB (optional für Windows/Gastzugriffe — siehe SMB-Hardening)
- SSH (nur falls benötigt — siehe SSH-Härtung)

AFP und FTP deaktivieren.

------------------------------------------------------------------------

### NFS

- **NFSv4.1** aktivieren (v4.0 abwählen)
- **Root Squash grundsätzlich aktivieren** — ohne Root Squash kann ein Linux-Client mit root-Zugang als beliebiger NAS-Benutzer auftreten
- Zugriffe nur für explizit bekannte Hosts erlauben (IP-Whitelist, kein Subnetz-Wildcard ohne Notwendigkeit)
- Jede der 8 Freigaben (Abschnitt 3) ist ein eigener NFS-Export — Root Squash und Host-Whitelist müssen pro Freigabe einzeln gesetzt werden (DSM > Freigegebene Ordner > Freigabe bearbeiten > NFS-Berechtigungen)
- **ki.lan nur mit Storage-Netz-IP whitelisten (`10.10.10.30`), nicht mit seiner Heimnetz-IP (`192.168.1.88`).** DSM prüft die Quell-IP des Clients: Da ki.lan den NAS über `storage` → `10.10.10.20` anspricht, kommt er mit `10.10.10.30` an. Fehlt diese IP in der Regel, scheitert der Mount mit `access denied by server`, obwohl Netzwerk und Firewall passen (so geschehen nach Umstellung der Namensauflösung auf das Storage-Netz). Kontrolle: `showmount -e storage` listet pro Export alle zugelassenen Hosts.

> **Ausnahme — `no_root_squash` für die technischen Root-Mount-Freigaben (`user1`, `user2`, `Media`, `Family`):** `mount --bind` läuft immer als root (CAP_SYS_ADMIN), unabhängig davon, welcher Benutzer den Bind-Mount letztlich nutzt. Bei aktivem Root Squash wird dieser root-Zugriff auf die anonyme NFS-Identität abgebildet, die auf den meisten Unterordnern keine Rechte hat — der Bind-Mount scheitert dann mit `Permission denied` beim Ermitteln des Quelltyps (empirisch bestätigt an `user1/Documents`: `Failed to determine type of bind mount source ... Permission denied`), obwohl derselbe Pfad für den eigentlichen Benutzer direkt einwandfrei lesbar ist. Für genau diese vier Freigaben (die ausschließlich als technische Root-Mounts unter `/mnt/nfs-roots/...` dienen, siehe Abschnitt „Mountpunkte") deshalb **Root Squash deaktivieren** ("Keine Zuordnung" / `no_root_squash`, DSM > Freigegebene Ordner > NFS-Berechtigungen). Root auf den ohnehin per IP-Whitelist zugelassenen, vertrauenswürdigen Clients erhält damit vollen Zugriff auf diese Exports — vertretbar, da root auf diesen Maschinen lokal ohnehin uneingeschränkten Zugriff hat. Für die direkt gemounteten Freigaben (`Pictures`, `Public`, `Scanner`) bleibt Root Squash aktiv, da dort keine Bind-Mounts nötig sind.

> **Sicherheitshinweis AUTH_SYS:** NFSv4 vertraut im Standardmodus (AUTH_SYS) den UID/GID-Angaben des Clients. Ein kompromittierter Linux-Client hätte damit Vollzugriff auf alle Dateien, die dem entsprechenden Benutzer gehören. Im abgeschirmten Heimnetz (kein Internetzugriff, VPN) ist das akzeptabel. Kerberos (krb5) wäre sicherer, ist aber im Heimnetz unverhältnismäßig aufwendig.

------------------------------------------------------------------------

### SMB-Härtung (falls SMB aktiviert)

Falls SMB für Windows- oder Gastzugriffe aktiviert wird:

- SMB-Signing aktivieren (DSM > Dateidienste > SMB > Erweitert)
- SMB-Encryption auf "optional" oder "required" setzen
- Mindest-SMB-Version: SMB 2 (SMB 1 deaktivieren)
- Gastzugriff deaktivieren
- Zugriff auf bekannte Hosts beschränken

------------------------------------------------------------------------

### SSH-Härtung

Falls SSH aktiviert:

- Nur Public-Key-Authentifizierung erlauben
- Passwort-Auth in `/etc/ssh/sshd_config` deaktivieren: `PasswordAuthentication no` (zusätzlich `ChallengeResponseAuthentication no` setzen, sonst möglicher PAM-Fallback auf Passwort)
- Root-Login deaktivieren: `PermitRootLogin no`
- SSH-Port ggf. ändern (Security through obscurity, aber reduziert Log-Rauschen)
- `MaxAuthTries 3` setzen — begrenzt Brute-Force-Versuche pro Verbindung
- Nach DSM-Updates `sshd_config` gegenprüfen — DSM überschreibt sie bei Major-Updates mitunter auf Standardwerte

#### Public Keys ohne Home-Verzeichnis

Da kein Benutzer-Home-Dienst läuft (Abschnitt 3), hat `user1-admin` kein `~/.ssh/authorized_keys`. Stattdessen ein home-unabhängiger Pfad über `AuthorizedKeysFile`:

```
# /etc/ssh/sshd_config
AuthorizedKeysFile /etc/ssh/authorized_keys/%u
```

Einrichtung:

```bash
sudo mkdir -p /etc/ssh/authorized_keys
sudo chmod 755 /etc/ssh/authorized_keys
sudo chown root:root /etc/ssh/authorized_keys

sudo cp id_ed25519_nas-admin.pub /etc/ssh/authorized_keys/user1-admin
sudo chmod 644 /etc/ssh/authorized_keys/user1-admin
sudo chown root:root /etc/ssh/authorized_keys/user1-admin

sudo synosystemctl restart sshd
```

Vorteil gegenüber `~/.ssh/authorized_keys`: Die Datei gehört `root` — der Benutzer selbst kann seinen eigenen Key nicht verändern, auch nicht bei kompromittiertem Account.

Eigener Key pro Zweck verwenden (nicht mit Keys für andere Dienste wie GitHub teilen — begrenzt den Schaden bei Kompromittierung).

#### Client-seitige `~/.ssh/config`

```
Host storage.lan
    User user1-admin
    IdentityFile ~/.ssh/id_ed25519_nas-admin
    IdentitiesOnly yes
```

`IdentitiesOnly yes` ist Pflicht: Ohne diese Zeile bietet der Client zusätzlich alle Standard-Keys und ssh-agent-Keys an — bei `MaxAuthTries 3` reicht das, um die Verbindung vor dem richtigen Key abzubrechen ("Too many authentication failures").

#### Service-Verwaltung (DSM 7)

DSM 7 nutzt `synosystemctl` (systemd-Wrapper) statt des älteren `synoservicectl` (DSM 5/6):

```bash
sudo synosystemctl restart sshd
```

`synosystemctl` kennt kein `status`-Subcommand — Status ggf. über die DSM-Oberfläche prüfen.

------------------------------------------------------------------------

### DSM-Firewall (DS718+)

Die eingebaute DSM-Firewall **muss** konfiguriert werden. Empfohlene Regeln (alle anderen Verbindungen ablehnen):

| Dienst | Port(s) | Protokoll | Erlaubte Quelle |
| --- | --- | --- | --- |
| NFS (Storage-Netz) | 2049, 111 | TCP (nur NFSv4.1; UDP nicht nötig, rpcbind/111 nur bei NFSv3-Fallback erforderlich) | 10.10.10.30 (ki.lan) |
| NFS (Heimnetz) | 2049, 111 | TCP (s.o.) | einzelne Desktop-PC-IPs im Heimnetz (Whitelist, kein Subnetz — je Freigabe unterschiedlich, von Admin selbst gepflegt) |
| SMB | 445 | TCP | Heimnetz (HA-Backup-Host, Drucker — feste IPs) |
| SSH | 22 | TCP | nur Management-Host |
| DSM Web | 5000, 5001 | TCP | Heimnetz / VPN |
| Hyper Backup | 6281 | TCP | DS224+ (10.10.10.21) |

Konfiguration: DSM > Systemsteuerung > Sicherheit > Firewall

### DSM-Firewall (DS224+)

Eigenständige DSM-Instanz, eigene Firewall-Konfiguration. DS224+ ist reines Backup-Ziel — kein NFS, kein SMB, keine Freigaben für Desktop-Clients nötig:

| Dienst | Port(s) | Protokoll | Erlaubte Quelle |
| --- | --- | --- | --- |
| Hyper Backup Vault | 6281 | TCP | DS718+ (10.10.10.20) |
| DSM Web | 5000, 5001 | TCP | Heimnetz / VPN |
| SSH | 22 | TCP | nur Management-Host (falls benötigt) |

Konfiguration: DSM > Systemsteuerung > Sicherheit > Firewall (auf DS224+ selbst)

------------------------------------------------------------------------

### SMB-Freigabe (HA-Backup, Drucker)

NFS bietet keine Zugriffsrechte pro Freigabe — für den Home-Assistant-Backup-Ordner und den Netzwerk-Scan-Ordner des Druckers wird daher SMB statt NFS genutzt.

**SMB-Version:** Drucker unterstützt SMB2 und SMB3 (SMB1 wäre zwar aktivierbar, wird aber nicht benötigt). Damit kann das Minimum ohne Kompromiss auf SMB2 gesetzt werden:

| Einstellung | Wert |
|---|---|
| Minimum SMB-Protokoll | SMB2 |
| Maximum SMB-Protokoll | SMB3 ("Größtmöglich") |
| SMB-Signierung | Aktivieren ("Wenn vom Client angefordert" oder "Erforderlich", falls Drucker und HA-Host das unterstützen) |
| Transportverschlüsselung | Aktivieren, falls Drucker/HA-Host das mitmachen (sonst Auswirkung auf Scan-Funktion prüfen) |
| Anonymer/Gast-Zugriff | Deaktivieren |

Konfiguration: DSM > Systemsteuerung > Dateidienste > SMB

**Freigaben und Rechte:**

- Eigene, separate Freigabe für den Drucker-Scan-Ordner und eine eigene für den HA-Backup-Ordner (nicht dieselbe Freigabe für beide).
- Eigenes Dienstkonto pro Zweck (Drucker, Home Assistant) statt eines gemeinsamen oder persönlichen Admin-Kontos — jeweils nur Lese-/Schreibrecht auf den jeweils eigenen Ordner (Least Privilege).
- Firewall-Regel für Port 445 (siehe Tabelle oben) auf die festen IPs von Drucker und HA-Host beschränken, nicht das gesamte Heimnetz.

------------------------------------------------------------------------

### Synology Photos (Foto-Upload vom Smartphone)

Kein separater Port — Synology Photos nutzt dieselben DSM-Web-Ports (5000/5001), die bereits für "Heimnetz / VPN" freigegeben sind.

Zu beachten:

- **QuickConnect ist deaktiviert** — die App muss manuell auf die NAS-Adresse (lokale IP zuhause, VPN-Adresse unterwegs) konfiguriert werden statt über die QuickConnect-ID.
- **Quelle als Subnetz, nicht Einzel-IP:** Anders als bei den fest zugeordneten Desktop-IPs (NFS/SMB) bekommt ein Smartphone eine dynamische IP aus dem VPN-Adresspool. Die DSM-Web-Regel (5000/5001) muss deshalb den gesamten VPN-Client-Bereich als Quelle erlauben, sonst funktioniert der Zugriff nach jedem VPN-Neuverbinden nicht mehr zuverlässig.
- **Öffentliche Freigabelinks** (Foto-Sharing mit Personen ohne VPN) sind nicht abgedeckt — das würde eine Portfreigabe direkt aus dem Internet erfordern und widerspricht dem Grundsatz "NAS nicht direkt aus dem Internet erreichbar". Für reinen Foto-Upload vom eigenen Handy nicht nötig.

------------------------------------------------------------------------

### 2FA

2FA schützt ausschließlich die **DSM-Weboberfläche** — NFS- und SMB-Zugriffe sind davon unabhängig.

- 2FA für alle DSM-Accounts empfohlen, mindestens für Admins
- Recovery Codes sicher (offline) speichern

------------------------------------------------------------------------

### Snapshots

Für alle wichtigen Freigaben:

- stündlich oder täglich
- Aufbewahrung z.B.
  - 24 Stunden
  - 30 Tage
  - 12 Monate

> Snapshots schützen vor versehentlichem Löschen, aber **nicht** vor Ransomware, die direkt auf DSM-Ebene zugreift. Snapshots sind kein Ersatz für Backup.

**Speicherplatzbedarf:** Snapshots sind Copy-on-Write — beim Erstellen wird nichts kopiert (Kosten ≈ 0), Speicherplatz wird erst belegt, wenn sich Daten danach ändern oder gelöscht werden (nur der geänderte Block bleibt für den Snapshot erhalten). Der Verbrauch hängt also von der Änderungsrate ab, nicht von der Gesamtgröße der Freigabe:

- Archiv-artige Freigaben (DMS-Scans, Fotos — überwiegend neue Dateien, kaum Überschreiben/Löschen) → günstig
- Freigaben mit viel Überschreiben/Löschen (z. B. HA-Backup-Ordner, wenn alte Backups regelmäßig ersetzt werden) → teurer

Lässt sich nicht seriös vorab kalkulieren — nach der Einrichtung den tatsächlichen Verbrauch pro Freigabe unter *Storage Manager > Snapshots* beobachten und die Aufbewahrungsdauer bei Bedarf anpassen. Als grober Startpuffer werden ca. 20 % freier Speicherplatz auf dem Volume für Snapshot-Overhead empfohlen.

------------------------------------------------------------------------

### Datenprüfung

Aktivieren:

- monatliche Datenbereinigung (Data Scrubbing)
- SMART Schnelltest wöchentlich
- SMART Intensivtest monatlich

------------------------------------------------------------------------

### Hyper Backup

Quelle:

    DS718+

Ziel:

    DS224+

Keine Synchronisation zwischen beiden NAS.

#### Benutzer für Hyper Backup

Auf der **Zielseite** (DS224+):

- Paket **Hyper Backup Vault** installieren
- Dedizierten Benutzer `backup-ds718` anlegen
- Diesem Benutzer Zugriff auf Hyper Backup Vault gewähren (DSM > Benutzer > Anwendungsberechtigungen)
- Kein Zugriff auf Dateifreigaben nötig — Hyper Backup Vault verwaltet seinen eigenen Speicherbereich

Auf der **Quellseite** (DS718+) läuft Hyper Backup unter dem Adminkonto — kein separater Benutzer nötig.

#### Backup-Härtung gegen Ransomware

DS224+ ist im selben Netzwerk wie DS718+. Bei einem Angriff könnte das Backup ebenfalls betroffen sein. Gegenmittel:

- **Hyper Backup Vault** auf DS224+ installieren und dort Immutability-Schutz aktivieren
- Alternativ: DS718+ hat nur Push-Zugriff auf DS224+ — kein Pull-Zugriff vom Produktivsystem auf das Backup

#### Backup-Verifikation

Hyper Backup bietet eine "Integrität prüfen"-Funktion. Regelmäßig einplanen:

- monatliche automatische Integritätsprüfung
- halbjährliches manuelles Test-Restore einer Stichprobe

#### 3-2-1-Regel

Das aktuelle Konzept erfüllt nur **2-1**: 2 Kopien, 1 Speichermedium-Typ, kein externer Standort.

Empfehlung (optional, für kritische Daten wie Finanzen, Verträge):

- Hyper Backup auf verschlüsselte externe Festplatte (Rotation, Offsite)
- oder Synology C2 Cloud Backup

------------------------------------------------------------------------

### Updates

DSM:

- automatisch herunterladen
- manuell installieren

Pakete:

- manuell aktualisieren

Neustarts bewusst durchführen.

------------------------------------------------------------------------

### Sicherheit (Überblick)

- kein QuickConnect
- kein Internetzugriff (NAS ist nicht direkt aus dem Internet erreichbar)
- VPN für Fernzugriff
- 2FA für alle Konten
- Recovery Codes sicher speichern
- DSM-Firewall konfiguriert (siehe Abschnitt oben)

------------------------------------------------------------------------

### USV / Stromabsicherung

Plötzlicher Stromausfall bei laufenden Schreibzugriffen kann trotz Btrfs CoW zu Inkonsistenzen führen. Empfehlung:

- **USV** (unterbrechungsfreie Stromversorgung) für DS718+ und DS224+ verwenden
- DSM unterstützt USV-Kommunikation via USB (automatisches sauberes Herunterfahren)

------------------------------------------------------------------------

## 5. Linux-Konfiguration

### Mountpunkte

**Wichtige Einschränkung (empirisch bestätigt):** DSMs NFSv4-Server erlaubt nur das Mounten der exakt konfigurierten Freigabe-Wurzel — keine Unterverzeichnisse davon. Getestet an `user1/Documents`, `Family/Templates` und `user2/Desktop`: alle drei scheitern mit `access denied by server`, während die jeweilige Freigabe-Wurzel selbst fehlerfrei mountet. ACLs und NFS-Exportoptionen sind dabei unauffällig — es handelt sich um eine grundsätzliche Einschränkung des NAS, nicht um ein Berechtigungsproblem. Ein direkter 1:1-NFS-Mount pro Kategorie (wie ursprünglich geplant) ist damit nicht möglich.

**Lösung — zweistufig, Root-Mount + Bind-Mount:**

1. Jede Freigabe, die mehrere Kategorien enthält (`user1`/`user2`, `Media`, `Family`), wird einmal komplett an einem technischen Ort außerhalb von `$HOME` gemountet (`/mnt/nfs-roots/<freigabe>`) — dieser Pfad wird nie direkt geöffnet, sondern dient nur als Quelle für Bind-Mounts.
2. Für jede Kategorie projiziert ein Linux-Bind-Mount (`mount --bind`, kein NFS, rein lokale Kernel-Funktion) das jeweilige Unterverzeichnis flach nach `$HOME` (z. B. `/mnt/nfs-roots/user1/Documents` → `~/Dokumente`).

Freigaben, die bereits 1:1 einer Kategorie entsprechen (`Pictures`, `Public`, `Scanner`), werden weiterhin **direkt** gemountet — kein Bind-Mount nötig.

> **Voraussetzung auf DSM-Seite — `no_root_squash`:** `mount --bind` läuft immer als root; bei aktivem Root Squash (DSM-Standard) wird dieser Zugriff auf eine anonyme Identität ohne Leserechte auf den meisten Unterordnern abgebildet, der Bind-Mount scheitert dann mit `Permission denied` (empirisch bestätigt). Root Squash muss deshalb für die vier technischen Root-Mount-Freigaben (`user1`, `user2`, `Media`, `Family`) deaktiviert werden — Details siehe Abschnitt „NFS" unter „DSM-Konfiguration".

> **Warum das trotzdem flach in `$HOME` aussieht und Snap-kompatibel bleibt:** Ein Bind-Mount macht das Zielverzeichnis für jeden Prozess ununterscheidbar von einem echten lokalen Verzeichnis — anders als bei einem Symlink wird der Quellpfad (`/mnt/nfs-roots/...`) beim Öffnen einer Datei nie aufgelöst oder sichtbar. Details siehe Snap-Hinweis im Abschnitt „XDG User Directories".

Persönliche Freigabe (`user1`, `user2`), je Kategorie ein Bind-Mount auf den technischen Root-Mount `/mnt/nfs-roots/{user}`:

    ~/Dokumente    ← {user}/Documents
    ~/Schreibtisch ← {user}/Desktop      (siehe Hinweis unten)
    ~/Projects     ← {user}/Projects
    ~/SmartHome    ← {user}/SmartHome
    ~/Finance      ← {user}/Finance
    ~/Archive      ← {user}/Archive

Gemeinsame Freigaben (für alle Linux-Clients gleich):

    ~/Musik        ← Media/Music        (Bind-Mount auf /mnt/nfs-roots/media)
    ~/Videos       ← Media/Videos       (Bind-Mount auf /mnt/nfs-roots/media)
    ~/Vorlagen     ← Family/Templates   (Bind-Mount auf /mnt/nfs-roots/family)
    ~/Bilder       ← Pictures           (direkter NFS-Mount, eigene Freigabe)
    ~/Öffentlich   ← Public             (direkter NFS-Mount, eigene Freigabe)
    ~/Scanner      ← Scanner            (direkter NFS-Mount, auch vom Drucker/Scanner und allen Usern genutzt)

`AI` wird aktuell nicht verwendet und daher auf den Linux-Desktop-Clients nicht gemountet.

> **`#recycle`-Papierkorb ausblenden:** Der DSM-Papierkorb (`#recycle`) liegt auf der Freigabe-Wurzel und ist damit nur bei den **direkt gemounteten** Freigaben (`Pictures`, `Public`, `Scanner`) für den Nutzer sichtbar — bei `user1`/`user2`/`Media`/`Family` liegt die Freigabe-Wurzel nur im nie direkt geöffneten technischen Root-Mount, dort stört er nicht. Da `#recycle` (anders als punktbeginnende Dateien) nicht automatisch von Nautilus/Dolphin versteckt wird, einmalig zentral auf dem NAS eine `.hidden`-Datei anlegen (gilt dann für alle Clients, kein Client-seitiges Konfigurieren nötig; unterstützt von Nautilus/GTK und Dolphin/KIO):
>
>     echo "#recycle" | sudo tee /volume1/Pictures/.hidden
>     echo "#recycle" | sudo tee /volume1/Public/.hidden
>     echo "#recycle" | sudo tee /volume1/Scanner/.hidden

Nicht mounten:

    ~/.config
    ~/.cache
    ~/.local
    ~/Downloads

> **Wichtig:** Anwendungen, die beim Start auf NFS-gemountete Verzeichnisse zugreifen (IDE-Projekte, Browser-Profil), können hängen bleiben, wenn der NAS nicht erreichbar ist. Konfigurationsdateien und Caches grundsätzlich lokal lassen.

> **Desktop über NFS:** `~/Schreibtisch` wird gemountet, obwohl einzelne Nutzer (z. B. Admin) den Desktop nur für Verknüpfungen verwenden und ihn lieber lokal hätten — andere Nutzer legen dort aber reguläre Dateien und Ordner ab, eine rein lokale Desktop-Ablage würde für diese Nutzer Daten unsichtbar vom Storage trennen. Deshalb einheitlich gemountet. Wenn der NAS beim Login nicht erreichbar ist, kann die Desktop-Umgebung beim Start kurz hängen, bis der Mount-Timeout greift. Im Normalbetrieb (NAS immer verfügbar) ist das unproblematisch.

> **Warnung — lokale Schattendaten unter Mountpunkten:** Wird unter einem (noch) nicht aktiven Mountpunkt lokal geschrieben (z. B. weil ein Tool das Verzeichnis vor dem ersten Mount-Trigger anlegt und befüllt — genau das ist uns mit `xdg-user-dirs-update --force` passiert), werden diese Dateien beim Mounten nicht gelöscht, sondern nur unsichtbar überlagert. Sie bleiben auf der lokalen Festplatte liegen und tauchen erst nach einem `umount` wieder auf — kann unbemerkt Speicherplatz belegen und beim Debuggen verwirren. Das gilt bei der zweistufigen Struktur für **beide** Ebenen — sowohl für den technischen Root-Mount (`/mnt/nfs-roots/...`) als auch für den Bind-Mount-Zielpfad in `$HOME`. Nach der Ersteinrichtung prüfen, ob dort lokale Altdaten liegen (`umount <pfad>` kurz testen, Inhalt darunter kontrollieren, danach wieder mounten).

------------------------------------------------------------------------

### Beispiel /etc/fstab

**Technische Root-Mounts** (einmal pro Mehrfach-Kategorie-Freigabe, liegen außerhalb `$HOME`, werden nie direkt geöffnet — Beispiel `user1`; `user2` analog mit `/mnt/nfs-roots/user2` und `/volume1/user2`):

    storage.lan:/volume1/user1 /mnt/nfs-roots/user1 nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage.lan:/volume1/Media /mnt/nfs-roots/media nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage.lan:/volume1/Family /mnt/nfs-roots/family nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

> **Voraussetzung: `no_root_squash` auf diesen vier Freigaben** (siehe Abschnitt „NFS" unter „DSM-Konfiguration") — sonst scheitern alle Bind-Mounts unten mit `Permission denied`.

**Bind-Mounts** (projizieren Unterverzeichnisse der Root-Mounts flach nach `$HOME`, Beispiel `user1`; `user2` analog mit `/mnt/nfs-roots/user2/...` und `/home/user2/...`):

    /mnt/nfs-roots/user1/Documents /home/user1/Dokumente none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-user1.mount 0 0

    /mnt/nfs-roots/user1/Desktop /home/user1/Schreibtisch none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-user1.mount 0 0

    /mnt/nfs-roots/user1/Projects /home/user1/Projects none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-user1.mount 0 0

    /mnt/nfs-roots/user1/SmartHome /home/user1/SmartHome none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-user1.mount 0 0

    /mnt/nfs-roots/user1/Finance /home/user1/Finance none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-user1.mount 0 0

    /mnt/nfs-roots/user1/Archive /home/user1/Archive none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-user1.mount 0 0

    /mnt/nfs-roots/media/Music /home/user1/Musik none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-media.mount 0 0

    /mnt/nfs-roots/media/Videos /home/user1/Videos none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-media.mount 0 0

    /mnt/nfs-roots/family/Templates /home/user1/Vorlagen none \
        bind,noauto,x-systemd.automount,x-systemd.mount-timeout=10,\
        x-systemd.requires=mnt-nfs\x2droots-family.mount 0 0

**Direkte Mounts** (eigene Freigabe, entspricht 1:1 einer Kategorie — kein Bind-Mount nötig):

    storage.lan:/volume1/Pictures /home/user1/Bilder nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage.lan:/volume1/Public /home/user1/Öffentlich nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage.lan:/volume1/Scanner /home/user1/Scanner nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

`user2` erhält dieselben gemeinsamen Mounts unter `/home/user2/...` (identische Quellpfade), einen eigenen technischen Root-Mount `/mnt/nfs-roots/user2` (statt `user1`) und die davon abgeleiteten Bind-Mounts unter `/home/user2/...`. `AI` wird aktuell nicht genutzt und daher hier nicht gemountet.

> **Unterverzeichnis-Mounts scheitern auf der DS718+:** Ein direkter NFS-Mount von z. B. `storage.lan:/volume1/user1/Documents` schlägt mit `access denied by server` fehl — DSMs NFSv4-Server akzeptiert nur exakt die konfigurierten Freigabe-Wurzeln als Mount-Ziel, unabhängig von ACL- oder Root-Squash-Einstellungen (empirisch an mehreren Freigaben bestätigt: `user1/Documents`, `Family/Templates`, `user2/Desktop`). Deshalb der Umweg über Root-Mount + Bind-Mount oben.

**`x-systemd.requires=` — exakten Unit-Namen vorher ermitteln, nicht von Hand tippen** (Tippfehler hier führen zu einem Bind-Mount auf ein leeres, nicht gemountetes Verzeichnis):

    systemd-escape --path --suffix=mount /mnt/nfs-roots/user1
    # → mnt-nfs\x2droots-user1.mount

Das sorgt dafür, dass beim ersten Zugriff auf z. B. `~/Dokumente` automatisch zuerst der zugehörige Root-Mount aktiviert wird. Ein aktiver Bind-Mount hält seinen Root-Mount außerdem automatisch „busy" — ein versehentliches Aushängen des Root-Mounts, während der Bind-Mount noch existiert, scheitert mit `EBUSY`, kein Risiko für unbemerkten Datenverlust durch falsche Reihenfolge.

Erklärung der wichtigsten Optionen:

| Option                        | Bedeutung                                                              |
|-------------------------------|-------------------------------------------------------------------------|
| `nfsvers=4.1`                 | Explizit NFSv4.1 verwenden                                              |
| `hard`                        | Prozess wartet auf NAS-Wiederkehr statt Fehler zurückzugeben            |
| `noatime`                     | Kein Access-Time-Update → weniger Schreibzugriffe                       |
| `rsize/wsize=1048576`         | Maximale Blockgröße → deutlich bessere Performance                      |
| `timeo=14,retrans=3`          | Timeout 1,4 s, 3 Wiederholungen bevor Hard-Retry                        |
| `x-systemd.mount-timeout=10`  | systemd wartet max. 10 s beim Mounten beim Boot                         |
| `bind`                        | Reiner lokaler Kernel-Bind-Mount, keine NFS-Option nötig/wirksam        |
| `x-systemd.requires=<unit>`   | Bind-Mount zieht beim Aktivieren zuerst den angegebenen Root-Mount hoch |

------------------------------------------------------------------------

### XDG User Directories

Da jede Kategorie direkt unter ihrem deutschen Standardnamen gemountet wird (Abschnitt "Mountpunkte"), entsprechen die Mountpunkte bereits den XDG-Standardpfaden — `~/.config/user-dirs.dirs` bleibt auf dem von `xdg-user-dirs-update` verwalteten Systemstandard, keine manuelle Anpassung nötig:

    XDG_DESKTOP_DIR="$HOME/Schreibtisch"
    XDG_DOWNLOAD_DIR="$HOME/Downloads"
    XDG_TEMPLATES_DIR="$HOME/Vorlagen"
    XDG_PUBLICSHARE_DIR="$HOME/Öffentlich"
    XDG_DOCUMENTS_DIR="$HOME/Dokumente"
    XDG_MUSIC_DIR="$HOME/Musik"
    XDG_PICTURES_DIR="$HOME/Bilder"
    XDG_VIDEOS_DIR="$HOME/Videos"

Das macht die Konfiguration robust gegen `xdg-user-dirs-update --force` (z. B. bei einem Distro-Update): Der Befehl überschreibt `user-dirs.dirs` zwar wieder mit exakt diesen Werten, aber das sind ohnehin die gewünschten Pfade — `mkdir -p` legt bei bereits vorhandenem Mountpunkt nichts Neues an. **Nie manuell mit `--force` aufrufen**, wenn eigene Pfade in der Datei stehen — das verwirft jede Anpassung kommentarlos und regeneriert die Datei rein aus `/etc/xdg/user-dirs.defaults` + Locale.

Eigene Ordner wie `Projects`, `SmartHome`, `Finance`, `Archive` haben kein XDG-Pendant und bleiben normale (gemountete) Verzeichnisse ohne Eintrag in `user-dirs.dirs`.

> **Snap-Vorsicht:** Dolphin, Firefox, Thunderbird und Spotify laufen auf dem Thinkpad als Snap. Deren `home`-Interface erlaubt Zugriff auf alles unterhalb `$HOME` — die Bind-Mount-Ziele (`~/Dokumente` usw., siehe Abschnitt „Mountpunkte") liegen dort und sind damit abgedeckt. Die technischen Root-Mounts (`/mnt/nfs-roots/...`), von denen die Bind-Mounts abgeleitet sind, liegen zwar außerhalb von `$HOME`, werden von den Apps aber nie direkt geöffnet: ein Bind-Mount macht den Quellpfad für den öffnenden Prozess unsichtbar — anders als ein Symlink, der aufgelöst wird und dessen Ziel deshalb ebenfalls `removable-media` bräuchte. Deshalb reicht das `home`-Interface weiterhin aus, ohne `snap connect` je App.

------------------------------------------------------------------------

### Benutzer & UID/GID

Auf allen Linux-Rechnern:

- identische Benutzer
- identische UID
- identische GID

Dadurch funktionieren NFS-Rechte problemlos.

> **Konkret festlegen:** Vor dem ersten NFS-Mount auf einem neuen Rechner UID/GID des Benutzers verifizieren (`id user1`). Ziel-UID und -GID dokumentieren — **nicht pauschal 1000:1000**, sondern die tatsächlichen DSM-internen UIDs verwenden (bei uns: `user1`=1026, `user2`=1028; DSM vergibt eigene UIDs unabhängig vom Linux-Client). Bei Abweichungen: `usermod -u <uid>` anpassen, bevor gemountet wird. Die GID muss dabei **nicht** zwingend angeglichen werden, solange die NAS-ACL-Regeln benutzerbasiert (`user:name:allow`) statt gruppenbasiert sind — nur die UID entscheidet dann über den Treffer.
>
> **Eigene UID ändern, während man selbst eingeloggt ist:** `usermod -u` schlägt fehl, solange noch ein Prozess mit der alten UID läuft (z. B. die eigene SSH-Sitzung) — auch `sudo su -` reicht nicht, weil die ursprüngliche Login-Shell im Hintergrund bestehen bleibt. Lösung: den Befehl über `systemd-run` entkoppelt von der aktuellen Sitzung ausführen, dann die Verbindung trennen und neu verbinden:
>
>     systemd-run --uid=0 --gid=0 --unit=fix-uid \
>       sh -c 'sleep 20; usermod -u <uid> <user>; find / -xdev -user <alte-uid> -exec chown -h <uid> {} \;'

------------------------------------------------------------------------

### rsync auf NFS-Mounts (ACL-verwaltete Freigaben)

`rsync -a` (Archive-Modus) versucht, Besitzer, Gruppe, Zeitstempel und Rechte-Bits der Quelle auf das Ziel zu übertragen (`-o -g -p -t`). Auf einer NFS-Freigabe, deren eigentliche Zugriffskontrolle über eine Synology-ACL läuft (nicht über die klassischen Unix-Bits), scheitern `chgrp`/`chown`/`chmod` für alle nicht-root-Nutzer regelmäßig — sie erfordern entweder Eigentümerschaft oder root, beides hat ein normaler NFS-Client-Nutzer nicht. Ergebnis: einzelne Fehlermeldungen (`failed to set permissions`, `chgrp ... Operation not permitted`) und potenziell eine überschriebene/zerstörte Ziel-ACL, falls `chmod` (`-p`) durchläuft.

`utime` (Zeitstempel, `-t`) ist davon **nicht** betroffen: Bei neu angelegten Zieldateien ist der kopierende Nutzer automatisch Eigentümer, `utime` auf eigene Dateien erfordert weder Sonderrechte noch root.

**Lösung:** Nur Besitzer/Gruppe/Rechte-Bits weglassen, Zeitstempel aber übertragen:

    rsync -rlv --progress --checksum -t \
      --no-perms --no-owner --no-group \
      <quelle>/ <ziel>/

`--checksum` (Änderungserkennung über Inhalts-Hash) sorgt zusätzlich dafür, dass künftige inkrementelle Läufe nicht auf `chmod`/`chown` angewiesen sind, um Änderungen zu erkennen.

> **ACL wird bei SSH/rsync-Zielen NICHT automatisch vererbt (empirisch bestätigt):** Anders als beim Kopieren über die DSM File Station übernehmen Dateien/Ordner, die per SSH direkt angelegt werden (z. B. via `rsync`), **nicht** automatisch die vererbbaren ACL-Einträge der Zielfreigabe — sie erhalten stattdessen nur eine minimale ACL mit dem kopierenden Benutzer (bei der Migration i. d. R. `user1-admin`) als einzigem Eintrag. Sichtbares Symptom: Zugriff auf die Freigabe-Wurzel funktioniert für andere Nutzer, aber `cd` in einen per rsync angelegten Unterordner scheitert mit `Permission denied`, obwohl die Unix-Bits (`ls -la`) unauffällig `rwxrwxrwx+` zeigen — das `+` zeigt an, dass zusätzlich eine ACL existiert, die die eigentliche Zugriffsentscheidung trifft, nicht die klassischen Bits. Bestätigt an der Freigabe `Pictures` nach der Migration aus Phase 2b (Unterordner `Bastian`).
>
> **Fix (nach jedem rsync-Lauf in eine ACL-verwaltete Freigabe zwingend):** ACL-Vererbung auf der Zielfreigabe nachträglich erzwingen — entweder in der File Station (Freigabe-Wurzel → Eigenschaften → Berechtigung → Änderungen auf „diesen Ordner, Unterordner und Dateien" anwenden) oder per SSH:
>
>     ssh user1-admin@storage.lan
>     /usr/syno/bin/synoacltool -enforce-inherit /volume1/<freigabe>
>
> Diagnose zum Vergleich: `/usr/syno/bin/synoacltool -get <pfad>` zeigt die tatsächliche ACL (Flag mit Bindestrich, `-get`, nicht `get`) — zuverlässiger als die File-Station-Berechtigungsanzeige, um den genauen Unterschied zwischen Root- und Unterordner-ACL zu erkennen.

------------------------------------------------------------------------

### PDF-Vorschauen und AppArmor (seit Ubuntu 26.04)

Auf den NFS-Freigaben gehören viele Dateien nicht dem angemeldeten Benutzer: per rsync migrierte Dateien gehören `user1-admin` (UID 1027), Scans dem Scanner-User (UID 1030), in gemeinsamen Freigaben liegen Dateien anderer Nutzer (z. B. `user2`, UID 1028). Lesen ist über die ACL bzw. Modus 777 problemlos möglich — **AppArmor prüft mit `owner`-Regeln aber zusätzlich, ob die Datei dem aufrufenden Benutzer gehört**, unabhängig von den Rechte-Bits. Seit dem Upgrade auf Ubuntu 26.04 (AppArmor 5.0.2) betrifft das die Thumbnailer.

Symptom: Die Datei lässt sich im Viewer öffnen, im Dateimanager wird aber keine Vorschau angezeigt. Vorschauen, die vor dem Upgrade erzeugt wurden, bleiben im Cache (`~/.cache/thumbnails`) erhalten und verdecken das Problem — auffällig wird es erst bei neuen oder noch nie angesehenen Dateien.

**Kubuntu / KDE (Dolphin)** — betroffen sind **alle** fremden PDFs. Dolphin erzeugt PDF-Vorschauen über Ghostscript (`gs`); dessen neues Profil `/etc/apparmor.d/gs` erlaubt Dateien unter `$HOME` und `/mnt` nur dem Eigentümer:

    owner file rw @{HOME}/**.@{gs_file_ext},
    owner file rw /mnt/**.@{gs_file_ext},

Okular öffnet PDFs über Poppler, nicht über `gs`, und ist daher nicht betroffen.

Diagnose (betroffenen Ordner in Dolphin öffnen, dann):

    journalctl -k -g 'apparmor="DENIED"' | grep 'profile="gs"' | tail -3
    # Einträge mit ouid ≠ eigene UID bestätigen die Ursache

Fix — lokale Ergänzung (bleibt bei Paket-Updates erhalten), nur Lesen ohne Besitzer-Prüfung:

    sudo tee -a /etc/apparmor.d/local/gs <<'EOF'
    # Allow thumbnailing of NFS files owned by other NAS users (read-only)
    file r @{HOME}/**.@{gs_file_ext},
    file r /mnt/**.@{gs_file_ext},
    EOF
    sudo apparmor_parser -r /etc/apparmor.d/gs
    rm -rf ~/.cache/thumbnails/fail

Danach Dolphin neu starten.

**Ubuntu / GNOME (Nautilus)** — betroffen sind nur fremde PDFs **ohne Dateiendung `.pdf`** (empirisch bestätigt). Das Profil von `papers-thumbnailer` (`/etc/apparmor.d/usr.bin.papers`) erlaubt Dateien mit bekannter Endung unabhängig vom Besitzer (`/**.[fFpP][dD][fF] r,`); für alle übrigen Dateien greift nur `owner @{HOME}/[^.]** r,`. GNOME kopiert die Datei für die Vorschau zudem nach `/tmp/gnome-desktop-file-to-thumbnail` (+ Endung des Originals) — ohne Endung fällt auch dieser Pfad unter eine `owner`-Regel. Beispiele: `Geburtsurkunde …` (ohne Endung) oder `… .pdf (1)` in `user2/Dokumente`. Fix: betroffenen Dateien die Endung `.pdf` geben, eine AppArmor-Anpassung ist nicht nötig.

> **Besitzer auf dem NAS korrigieren löst das Problem nicht allgemein:** In den persönlichen Freigaben ließe sich der Besitzer zwar angleichen (`chown -R user1 /volume1/user1` als `user1-admin`, ACL bleibt erhalten), in gemeinsamen Freigaben (`Scanner`, `Family`, `Media`, `Pictures`, `Public`) gehören Dateien aber immer verschiedenen Nutzern. Die AppArmor-Ergänzung auf den KDE-Clients ist daher der eigentliche Fix.

------------------------------------------------------------------------

## 6. Netzwerk

Empfehlung:

    LAN1 -> Heimnetz
    LAN2 -> Storage-Netz

Storage-Netz:

    10.10.10.0/24

Beispiel:

    DS718+      10.10.10.20
    DS224+      10.10.10.21
    KI-Server   10.10.10.30

Hyper Backup und NFS zwischen Servern laufen über dieses Netz.

Der Switch verbindet ausschließlich diese drei Geräte — kein Uplink ins Heimnetz, kein Internetzugang. Da DS718+ und DS224+ je zwei 1GbE-Ports haben, reicht ein einfacher **1GbE-Switch** (3–4 Ports, unmanaged).

------------------------------------------------------------------------

### KI-Server (ki.lan) — Umsetzungsstatus

- OS: Ubuntu 26.04 LTS (Upgrade von 24.04), Netzwerkverwaltung über **systemd-networkd** (netplan-Renderer) — kein NetworkManager/`nmcli` installiert
- Bestehende Heimnetz-NIC: `enp6s0` (DHCP, `192.168.1.x`)
- Storage-Netz-NIC: `enp7s0f1`, statisch konfiguriert über eigene Netplan-Datei (nicht die cloud-init-verwaltete `50-cloud-init.yaml`, da diese beim Boot überschrieben werden kann):

```yaml
# /etc/netplan/60-storage-net.yaml (chmod 600, root:root — sonst Netplan-Warnung "Permissions too open")
network:
  version: 2
  ethernets:
    enp7s0f1:
      dhcp4: no
      addresses:
        - 10.10.10.30/24
```

  Anwenden: `sudo netplan apply`

- **Verbindung verifiziert:** `ping -I enp7s0f1 10.10.10.20` (DS718+) und `10.10.10.21` (DS224+) — beide erreichbar, 0 % Paketverlust
- Nächster Test nach Einrichtung der NFS-Exporte: `nc -zv 10.10.10.20 2049` / `111` — bestätigt, dass die DSM-Firewall-Regel greift
- **Namensauflösung `storage` → Storage-Netz:** statischer Eintrag in `/etc/hosts`, damit NFS über `enp7s0f1` läuft (ohne Eintrag löst `storage` per DNS auf die Heimnetz-IP des NAS auf): `10.10.10.20 storage`

  Derselbe Eintrag steht zusätzlich in `/etc/cloud/templates/hosts.debian.tmpl` — falls cloud-init `/etc/hosts` beim Boot neu generiert (`manage_etc_hosts: true`), bleibt er so erhalten.

  Prüfen: `getent hosts storage` → `10.10.10.20`, `ip route get 10.10.10.20` → `dev enp7s0f1 src 10.10.10.30`

- **NFS-Mounts über Storage-Netz verifiziert** (inkl. Reboot): alle `/mnt/nas/*`-Freigaben mounten per `x-systemd.automount`

------------------------------------------------------------------------

### Single Point of Failure

Die DS718+ ist der einzige Produktivspeicher. Szenarien und Konsequenzen:

| Ereignis                              | Auswirkung                                    | Gegenmittel                      |
|---------------------------------------|-----------------------------------------------|----------------------------------|
| Eine Festplatte defekt                | Kein Datenverlust (SHR/RAID 1), NAS läuft     | Festplatte tauschen              |
| Beide Festplatten defekt              | Datenverlust — Restore von DS224+             | Hyper Backup                     |
| NAS-Hardware defekt (Controller/NT)   | Datenzugriff unterbrochen bis Reparatur       | Backup auf DS224+, Restore nötig |
| DSM-Korruption                        | Datenzugriff unterbrochen                     | DSM neu installieren             |

> RAID ist **kein Backup**. Es schützt nur vor Festplatten-Einzelausfall.

------------------------------------------------------------------------

## 7. Langfristige Struktur

    Linux-PCs
            │
            ├───────────── NFS ─────────────┐
            │                               │
            ▼                               │
          DS718+                            │
          Produktiv                         │
            │                               │
            └──── Hyper Backup ─────────────┘
                            │
                            ▼
                         DS224+
                          Backup

### Ergebnis

- zentrale Datenhaltung
- keine Synchronisation zwischen PCs
- persönliche und gemeinsame Daten getrennt
- Snapshots gegen versehentliche Änderungen
- Backup getrennt vom Produktivsystem
- saubere Linux-Integration per NFS

------------------------------------------------------------------------

## 8. Inbetriebnahme-Checkliste

### Phase 1 — DS718+ einrichten

- [ ] Festplatten einbauen, DSM installieren
- [ ] SHR-Volume mit Btrfs erstellen
- [ ] Standardkonto `admin` deaktivieren, Adminkonto `user1-admin` anlegen
- [ ] Benutzerkonto `user1` anlegen, Gruppen einrichten
- [ ] Freigaben `user1`, `user2`, `Scanner`, `Family`, `Media`, `Public`, `AI` erstellen, Nutzer-/Gruppenrechte je Freigabe setzen
- [ ] NFSv4.1 aktivieren, Root Squash aktivieren (außer `user1`, `user2`, `Media`, `Family` — dort `no_root_squash`, siehe Abschnitt „NFS"), Hosts whitelisten
- [ ] DSM-Firewall konfigurieren
- [ ] 2FA für alle Accounts einrichten
- [ ] Snapshots für alle Freigaben konfigurieren
- [ ] Datenbereinigung (monatlich) und SMART-Tests planen
- [ ] QuickConnect deaktivieren

### Phase 2 — Daten migrieren

#### 2a — Daten von DS224+ auf DS718+ (NAS-zu-NAS über Storage-Netz)

Per SSH auf DS718+ einloggen und rsync von dort starten — belastet den Desktop nicht:

    rsync -av --progress --ignore-existing \
        --exclude '@*' \
        user1@10.10.10.21:/volume1/Backup/user1/ \
        /volume1/user1/

Für jeden weiteren Benutzer analog wiederholen. `--ignore-existing` stellt sicher, dass bereits vorhandene Dateien auf DS718+ nicht überschrieben werden. `--exclude '@*'` schließt Synology-Systemordner (`@eaDir`, `@tmp` etc.) aus.

#### 2b — Daten von Linux-PCs auf DS718+

Die finalen Mountpunkte (Phase 5) liegen direkt unter den bekannten lokalen Namen (z. B. `~/Dokumente`) — ein NFS-Mount an derselben Stelle würde den lokalen Inhalt beim Migrieren nur verdecken, nicht zusammenführen. Migration deshalb **ohne lokalen NFS-Mount**, direkt per SSH+rsync in den exakten Zielunterordner auf der DS718+ (empirisch bestätigt funktionsfähig) — das umgeht die NFS-Unterverzeichnis-Mount-Einschränkung (siehe Warnung im Abschnitt „Beispiel /etc/fstab") von vornherein, da reiner SSH-Dateizugriff nicht über den NFS-Export läuft und dieser Einschränkung damit gar nicht erst unterliegt:

    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Dokumente/    user1-admin@storage.lan:/volume1/user1/Documents/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Schreibtisch/ user1-admin@storage.lan:/volume1/user1/Desktop/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Projects/     user1-admin@storage.lan:/volume1/user1/Projects/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/SmartHome/    user1-admin@storage.lan:/volume1/user1/SmartHome/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Finance/      user1-admin@storage.lan:/volume1/user1/Finance/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Archive/      user1-admin@storage.lan:/volume1/user1/Archive/

Für `Media`, `Family` und `Pictures` analog, sowie für `user2` mit `/volume1/user2/...` als Ziel:

    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Musik/    user1-admin@storage.lan:/volume1/Media/Music/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Videos/   user1-admin@storage.lan:/volume1/Media/Videos/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Vorlagen/ user1-admin@storage.lan:/volume1/Family/Templates/
    rsync -rlv --progress --checksum -t --no-perms --no-owner --no-group \
      ~/Bilder/   user1-admin@storage.lan:/volume1/Pictures/

Voraussetzung: `user1-admin` ist per SSH-Key erreichbar (Abschnitt 4, „Public Keys ohne Home-Verzeichnis") und hat als Mitglied der `administrators`-Gruppe Zugriff auf alle Freigaben, auch die persönliche Freigabe `user1`. Vor dem vollständigen Lauf mit einer einzelnen Testdatei prüfen, dass `user1` (nicht nur `user1-admin`) die neu angelegten Dateien über die ACL korrekt sieht/bearbeiten kann.

> **Nach jedem rsync-Lauf zusätzlich zwingend:** ACL-Vererbung auf der Zielfreigabe erzwingen (`synoacltool -enforce-inherit`, siehe Abschnitt „rsync auf NFS-Mounts" → „ACL wird bei SSH/rsync-Zielen NICHT automatisch vererbt"). Eine einzelne Testdatei allein deckt das Problem nicht zuverlässig auf.

> **`-a` vermeiden:** `-a` (Archive-Modus) versucht zusätzlich `chmod`/`chown` auf das Ziel anzuwenden (`-p`/`-o`/`-g`) — das scheitert als normaler (nicht-root) NFS-Client-Nutzer auf der ACL-verwalteten Zielfreigabe mit „Operation not permitted" (siehe Abschnitt „rsync auf NFS-Mounts"). `-t` (Zeitstempel) ist dagegen unproblematisch, da die Zieldateien hier neu angelegt werden und der Ersteller automatisch Eigentümer ist.

Erst danach die lokalen Ordner entfernen (siehe Warnung „lokale Schattendaten" im Abschnitt „Mountpunkte") und in Phase 5 die finalen Root- und Bind-Mount-Einträge setzen.

#### 2c — Verifikation

- [ ] Stichproben: zufällige Dateien aus DS224+ mit DS718+ vergleichen
- [ ] `rsync --dry-run` nochmals ausführen — keine zu kopierenden Dateien mehr = Transfer vollständig

### Phase 3 — DS224+ auf Btrfs umstellen

- [ ] Sicherstellen: alle Daten sind auf DS718+ vorhanden und geprüft
- [ ] DS224+ Volume löschen und neu als **Btrfs** erstellen
- [ ] Hyper Backup Vault auf DS224+ installieren
- [ ] Benutzer `backup-ds718` anlegen, Anwendungsberechtigung für Hyper Backup Vault setzen

### Phase 4 — Backup einrichten

- [ ] Hyper Backup auf DS718+ einrichten, Ziel: DS224+ (Benutzer `backup-ds718`)
- [ ] Erstes vollständiges Backup durchführen
- [ ] Backup-Integrität prüfen (Hyper Backup > Integrität prüfen)
- [ ] Backup-Zeitplan und Aufbewahrungsregeln konfigurieren

### Phase 5 — Linux-Clients einrichten

- [ ] UID/GID des Benutzers `user1` auf jedem Client prüfen und angleichen
- [ ] Storage-Netz-NIC konfigurieren (10.10.10.x)
- [ ] Auf DSM prüfen: `no_root_squash` für `user1`, `user2`, `Media`, `Family` gesetzt (Voraussetzung für Bind-Mounts, siehe Abschnitt „NFS")
- [ ] `/etc/fstab` Einträge setzen: technische Root-Mounts, Bind-Mounts und direkte Mounts (siehe Abschnitt „Beispiel /etc/fstab") — Unit-Namen für `x-systemd.requires=` vorher per `systemd-escape --path --suffix=mount <root-mountpunkt>` ermitteln, nicht von Hand tippen
- [ ] Nach fstab-Änderungen `sudo systemctl daemon-reload` ausführen, bevor die neuen Mounts getestet werden
- [ ] Vor dem ersten Mount prüfen, dass unter den Zielverzeichnissen (Root-Mountpunkte **und** Bind-Mount-Ziele) keine lokalen Altdaten liegen (siehe Warnung „lokale Schattendaten" im Abschnitt „Mountpunkte")
- [ ] `~/.config/user-dirs.dirs` **nicht** anpassen — Systemstandard passt bereits zur neuen Mount-Struktur
- [ ] NFS-Mounts testen
- [ ] Nur KDE-Clients: AppArmor-Ergänzung `/etc/apparmor.d/local/gs` für PDF-Vorschauen fremder Dateien setzen (siehe Abschnitt „PDF-Vorschauen und AppArmor")

### Phase 6 — KI-Server (ki.lan) einrichten

- [x] Storage-Netz-NIC konfigurieren (10.10.10.30)
- [x] `storage` → `10.10.10.20` in `/etc/hosts` und `/etc/cloud/templates/hosts.debian.tmpl` eintragen
- [x] NFS-Berechtigungen aller Freigaben auf `10.10.10.30` umstellen (Heimnetz-IP `192.168.1.88` entfernt), NFS für `Public` und `AI` aktivieren
- [x] `/etc/fstab` Einträge für alle `/mnt/nas/*`-Freigaben setzen (`user1`, `user2`, `scanner`, `family`, `media`, `pictures`, `public`, `ai`)
- [ ] dms-extractor Compose-Datei mit Bind-Volume aktualisieren
- [ ] `alice.dms_watched_folders` Eintrag in Datenbank setzen
- [ ] DMS-Pipeline testen

------------------------------------------------------------------------

## 9. DMS-Integration (Alice-Projekt)

Dokumente gelangen über verschiedene Wege auf den Speicher — Scanner, Smartphone, Downloads, E-Mail-Anhänge. Der Ablageort ist nicht vorhersehbar. Daher bindet ki.lan alle relevanten Freigaben ein (persönliche Benutzer-Freigaben und die gemeinsamen Bereichs-Freigaben); die konkreten DMS-Watchfolders werden über das Alice-DMS-Management konfiguriert.

### NFS-Mounts auf ki.lan (KI-Server)

Eintrag in `/etc/fstab` auf ki.lan (Pfadschema: `/mnt/nas/{user}` für persönliche, `/mnt/nas/{bereich}` für gemeinsame Freigaben):

    storage:/volume1/user1 /mnt/nas/user1 nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage:/volume1/Scanner /mnt/nas/scanner nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage:/volume1/Family /mnt/nas/family nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage:/volume1/Media /mnt/nas/media nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage:/volume1/Pictures /mnt/nas/pictures nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage:/volume1/Public /mnt/nas/public nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

    storage:/volume1/AI /mnt/nas/ai nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

Für weitere Benutzer analog (`user2` ist bereits in `nas-volumes.yml` eingetragen):

    storage:/volume1/user2 /mnt/nas/user2 nfs4 \
        noauto,x-systemd.automount,x-systemd.mount-timeout=10,_netdev,\
        nfsvers=4.1,hard,noatime,rsize=1048576,wsize=1048576,timeo=14,retrans=3 0 0

Mountpunkte anlegen:

    sudo mkdir -p /mnt/nas/user1 /mnt/nas/user2 /mnt/nas/scanner /mnt/nas/family /mnt/nas/media /mnt/nas/pictures /mnt/nas/public /mnt/nas/ai

### Docker-Zugriff (dms-extractor)

Die Volumes sind zentral in `docker/compose/automations/nas-volumes.yml` definiert und werden per `extends` in jeden dms-extractor eingebunden:

    # docker/compose/automations/nas-volumes.yml
    services:
      nas-base:
        volumes:
          - /mnt/nas/user1:/mnt/nas/user1:ro
          - /mnt/nas/user2:/mnt/nas/user2:ro
          - /mnt/nas/scanner:/mnt/nas/scanner:ro
          - /mnt/nas/family:/mnt/nas/family:ro
          - /mnt/nas/media:/mnt/nas/media:ro
          - /mnt/nas/pictures:/mnt/nas/pictures:ro
          - /mnt/nas/public:/mnt/nas/public:ro
          - /mnt/nas/ai:/mnt/nas/ai:ro

    # In jedem dms-extractor-xxx/compose.yml:
    extends:
      file: ../nas-volumes.yml
      service: nas-base

> Neuen Benutzer oder Freigabe hinzufügen: nur `nas-volumes.yml` und die fstab auf ki.lan anpassen — alle Container erben die Änderung automatisch.

### Benutzer/Rechte auf NAS-Ebene

Der dms-extractor-Container läuft als bestimmter UID (prüfen: `docker inspect`). Auf DS718+ einen dedizierten Benutzer `ki-server` anlegen und diesem Leserecht auf alle relevanten Freigaben geben. UID dieses Benutzers mit der Container-UID abgleichen.

### DMS-Watchfolders

Die zu überwachenden Verzeichnisse werden **nicht hardcodiert**, sondern über das Alice-DMS-Management in `alice.dms_watched_folders` gepflegt. Beispieleinträge:

    INSERT INTO alice.dms_watched_folders (path, label, sort_order)
    VALUES
      ('/mnt/nas/scanner',           'NAS Scanner',       10),
      ('/mnt/nas/public',            'NAS Austausch',     20),
      ('/mnt/nas/user1/Documents', 'Admin Dokumente', 30),
      ('/mnt/nas/user1/Finance',   'Admin Finanzen',  40);

> Die Pfade beziehen sich auf den Container-internen Pfad (identisch mit dem Host-Pfad bei Bind-Volumes).

### Ablauf-Übersicht

    Dokumente (Scanner / Smartphone / Download / E-Mail)
          │
          ▼
    DS718+ (Freigabe je Bereich: Scanner/Family/Media/Public/AI oder {user}/*)
          │
          ▼ (NFS, gemountet auf ki.lan)
    /mnt/nas/{bereich}/  oder  /mnt/nas/{user}/
          │
          ▼ (Bind-Volume)
    dms-extractor Container
          │
          ▼
    DMS-Pipeline (Weaviate, PostgreSQL)
