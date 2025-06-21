# **Product Requirements Document (PRD) – Vinted Price Alert Bot (MVP)**

> **Mission Statement**\
> Bargain‑hunting on Vinted ist zeit‑ und nerven­aufwändig. Der Vinted Price Alert Bot liefert dir *in Echtzeit* Push‑Benachrich­tigungen zu Second‑Hand‑Schnäppchen, die klar unter dem markt­üblichen Median­preis liegen – gefiltert nach deiner Lieblings­marke, Größe und Kleidungsart. So verpasst du kein gutes Angebot mehr und sparst Geld sowie Scroll‑Zeit.

---

## 1 · Scope & Goals

| Goal ID | Ziel                                 | Messbare Erfolgs­kriterien                                                |
| ------- | ------------------------------------ | ------------------------------------------------------------------------- |
|  G‑01   | **Schnäppchen finden**               | ≥ 1 Qualifizierter Alert/Tag pro Query innerhalb von 7 Tagen Pilotbetrieb |
|  G‑02   | **Zeit sparen**                      | < 5 Min Setup‑Zeit für eine neue Query, < 30 Sek Alert‑Latenz             |
|  G‑03   | **Self‑hostable & Privacy‑friendly** | Läuft komplett auf eigenem Server/Raspberry Pi; alle Daten bleiben lokal  |

---

## 2 · Functional Requirements (FR)

Die Tabelle basiert auf der existierenden Code‑Basis `Fuyucch1/Vinted-Notifications` und ergänzt Preis‑Intelligenz.

| FR‑ID     | Beschreibung                  | User Story                                                                              | Akzeptanz­kriterium                                             |
| --------- | ----------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **FR001** | Neue Query anlegen            | *Als User* möchte ich eine gefilterte Vinted‑URL eingeben können, um sie zu überwachen. | URL wird gespeichert, Scheduler startet ≤ 1 min später          |
| **FR002** | Query bearbeiten              | *Als User* möchte ich Filter ändern können.                                             | Änderungen werden sofort wirksam (< 1 min)                      |
| **FR003** | Query deaktivieren/löschen    | *Als User* möchte ich eine Query pausieren oder entfernen.                              | Inaktive Queries produzieren keine Requests                     |
| **FR004** | Query‑Dashboard               | *Als User* will ich eine Übersicht aller Queries.                                       | Tabelle listet URL, Threshold %, Status, letzte Prüfung         |
| **FR005** | Threshold % setzen            | *Als User* möchte ich den Prozent­wert unter Median definieren (Default = 60 %).        | Wert wird persistiert & angewandt                               |
| **FR006** | Preis‑Historie speichern      | *Als System* will ich historische Preise protokollieren.                                | `(category_key, price, ts)` werden in `price_history` gesichert |
| **FR007** | Rollierenden Median berechnen | *Als System* will ich den Median (30 Tage / 500 Einträge) pro Category.                 | Median‑Cache aktualisiert ≤ 5 min                               |
| **FR008** | Threshold‑Check               | *Als System* vergleiche Item‑Preis gegen `median × threshold`.                          | Nur passende Items erreichen FR009                              |
| **FR009** | Telegram‑Alert                | *Als User* erhalte ich eine Nachricht mit Bild, Preis & Link.                           | Alert ≤ 30 Sek nach Item‑Erkennung                              |
| **FR010** | Duplikat‑Vermeidung           | *Als User* bekomme ich jedes Item max. 1×.                                              | Item‑ID in `seen_items` verhindert Wiederholung                 |
| **FR011** | Web‑UI Auth                   | *Als Betreiber* will ich Passwort­schutz.                                               | HTTP 401 ohne gültige Credentials                               |
| **FR012** | System‑Status                 | *Als Betreiber* will ich Logs & Health‑Check.                                           | UI zeigt Up‑/Down‑Status & letzte Fehler                        |

---

## 3 · Non‑Functional Requirements (NFR)

| NFR‑ID     | Requirement            | Acceptance Criteria                                                              |
| ---------- | ---------------------- | -------------------------------------------------------------------------------- |
|  **NFR01** | **Performance**        | ≤ 5 min Poll‑Intervall pro Query, Alert‑Latenz ≤ 30 Sek                          |
|  **NFR02** | **Reliability**        | Mean Time Between Failure ≥ 7 Tage; Auto‑Retry mit Back‑off bei Fehlern          |
|  **NFR03** | **Security & Privacy** | Secrets via `.env`/Docker Secrets; HTTPS für Web‑UI; keine Preis‑Daten an Dritte |
|  **NFR04** | **Portability**        | Docker‑Compose oder Python 3.11; lauffähig auf RasPi 4 (2 GB RAM)                |
|  **NFR05** | **Observability**      | strukturierte Logs (JSON), Prometheus‑Metrics Endpoint                           |

---

## 4 · System Architecture

```
┌──────────────┐     (1) HTTPS Pull
│  Web  UI     │◄──────────────────┐
└──────────────┘                   │
      ▲   ▲                       ▼ (2) REST/WebSocket
      │   │                ┌────────────────┐
      │   └──Query CRUD────► FastAPI Server │
      │                    └────────────────┘
      │                        ▲    ▲
      │                        │    │ (3) Async Tasks
┌──────────────┐   (4) SQL   ┌─────────────────┐      
│   SQLite     │◄────────────┤  Scheduler &    │
└──────────────┘             │  Price Engine   │──(5) sendPhoto()──► Telegram Bot API
                             └─────────────────┘
```

1. User interagiert über das Vue‑basierte Web‑UI.
2. FastAPI liefert REST‑Endpoints & WebSockets für Live‑Logs.
3. Ein `asyncio`‑Scheduler ruft die inoffizielle Vinted‑API ab, persistiert Items & Preise.
4. SQLite speichert `queries`, `price_history`, `seen_items`.
5. Alerts gehen via `python‑telegram‑bot` an den User.

---

## 5 · Data Model

| Table           | Primary Key          | Wichtige Spalten                                                   | Zweck                                    |
| --------------- | -------------------- | ------------------------------------------------------------------ | ---------------------------------------- |
| `queries`       | `id` (UUID)          | `name`, `vinted_url`, `threshold_pct`, `poll_interval_s`, `active` | Konfiguration der Suchanfragen           |
| `price_history` | `(category_key, ts)` | `price`                                                            | Historische Preise für Median‑Berechnung |
| `seen_items`    | `item_id`            | `query_id`, `first_seen_ts`                                        | Duplicate‑Filter                         |
| `system_logs`   | `log_id`             | `level`, `message`, `ts`                                           | UI‑Log‑Viewer                            |

*`category_key`*\* = `` + `` + \**`catalog_title`*

---

## 6 · Algorithmic Details

1. **Median‑Window**: 30 Kalendertage oder maximal 500 Preispunkte, whichever first.
2. **Insertion**: Bei jedem neu gefundenen Item ➜ `price_history.insert(...)`.
3. **Eviction**: Nightly Job löscht Zeilen `< now‑30d` oder über 500 Datensätze/Category.
4. **Price Check**: `if price ≤ median × (threshold_pct / 100): alert()`.
5. **Caching**: Median pro Category im RAM – TTL = 1 h.
6. **Complexity**: O(log n) für Insert (SortedList) + O(1) Median‑Lookup.

---

## 7 · UI / UX Flows

1. **Add Query**\
   *Dashboard → „Add Query“ → Modal:*
   - Feld „Name“
   - Feld „Vinted‑URL“
   - Feld „Threshold %“ (Default 60)
   - Feld „Poll Interval [sec]“ (Default 300)\
     → *Save*.
2. **Edit Query**\
   Klick auf 🖉‑Icon → Modal mit voraus­gefüllten Werten → *Save*.
3. **Live Logs**\
   Seitenleiste „Logs“ zeigt Stream (WebSocket).
4. **Auth Flow**\
   HTTP Basic Auth → Login‑Dialog im Browser; Fehlversuch 401.

---

## 8 · Test & Acceptance Criteria

| Test Layer  | Tooling                | Success Metric                                   |
| ----------- | ---------------------- | ------------------------------------------------ |
| Unit Tests  | pytest                 | ≥ 90 % Coverage der Price‑Engine                 |
| Integration | pytest‑asyncio + httpx | API End‑to‑End ohne Fehler ✔                     |
| E2E         | Playwright             | Add‑Query‑Flow < 15 Sek, Alert‑Flow funktioniert |
| Load Test   | k6                     | 50 gleichzeitige Queries → < 80 % CPU auf RasPi  |

Acceptance erfolgt, wenn alle FR & NFR erfüllt und alle Tests auf GitHub Actions *green* sind.

---

## 9 · Deployment & CI/CD

- **Docker Image** (`Dockerfile`) baut FastAPI + Vue UI.
- **docker‑compose.yml** startet `web`, `scheduler` (same container), `sqlite` (volume), `nginx` (TLS).
- **GitHub Actions**:
  - Job 1 · Lint + Unit Tests
  - Job 2 · Build & Push Image → GHCR
  - Job 3 · Deploy via SSH to RasPi (optional).
- **Observability**: Exporter Endpoint `/metrics` → Prometheus + Grafana Dashboard.

---

## 10 · Risiken & Annahmen

- **API‑Breakage**: Vinted ändert JSON -> Bot down · Mitigation: Schema‑Version Check + Alert.
- **Legal**: Inoffizielles API → nur private Nutzung.
- **Spam**: Falscher Threshold → zu viele Alerts · Default 60 %.

---

## 11 · Out of Scope (MVP)

- Multi‑User‑Roles, OAuth etc.
- Auto‑Checkout / Kauf.
- Öffentliche/kommerzielle SaaS.

---

## 12 · MVP Success Checklist

1. *Setup*: Frisches RasPi‑Image + `docker‑compose up` → Dashboard erreichbar.
2. *Query*: „Armani Pullover XS“ angelegt.
3. *Median*: ≥ 50 Preispunkte, Median korrekt.
4. *Alert*: Item ≥ 40 % unter Median → Telegram Nachricht ≤ 30 Sek.
5. *Stabilität*: 168 h (7 Tage) Dauerbetrieb ohne manuellen Eingriff, CPU < 50 %.

---

### Raspberry Pi Deployment Notes (added 2025‑06‑21)

| Aspekt                | Anforderung                                                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Produktiv‑Host**    | Raspberry Pi 5 Model B (ARMv8, 4 GB RAM empfohlen)                                                                                        |
| **OS**                | Raspberry Pi OS Bookworm 64‑bit (Debian 12) oder kompatibles ARM64‑Debian                                                                 |
| **Python**            | 3.11.x (via `sudo apt install python3.11 python3.11-venv` oder `pyenv`)                                                                   |
| **Service‑Start**     | Systemd‑Unit `vinted-bot.service` (Beispiel‑Unit in /deploy)                                                                              |
| **Daten‑Pfad**        | `/opt/vinted-bot/data` (SQLite, Logs) mit wöchentlichem Backup via `cron`                                                                 |
| **Ports**             | 8000/tcp intern (Web-UI), optional 443/tcp extern (wenn Webhook)                                                                          |
| **Ressourcen‑Budget** | < 150 MB RAM, < 5 % CPU (Cron‑Polling alle 60 s)                                                                                          |
| **Deployment**        | Option A: `git pull && systemctl restart vinted-bot`  •  Option B: Docker multi‑arch Image (`docker buildx build --platform linux/arm64`) |

> **Hinweis für Entwickler\:innen:** Das PRD bleibt sonst unverändert. Einzelne Pfade/Ports sind im `config.py` parametrierbar, sodass Laptop‑Dev und Raspberry‑Prod ohne Code‑Änderung funktionieren (ENV‑Variablen).
