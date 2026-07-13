# Receipt Analyser

Parses receipts (PDF and photographed/scanned images) from multiple stores
-- Coles, Woolworths, JB Hi-Fi, Kmart, Ambeys, and any new store you add --
and saves items, prices, dates, and gift card balances into a database.
Includes per-store item price analytics and gift card balance tracking.

By default the project connects to an external SQL Server database. If
you'd rather not manage a separate SQL Server instance, see **Section 2**
for a Postgres alternative that runs entirely inside Docker alongside the
app -- no external database required.

---

## 1. Prerequisites

- Docker + Docker Compose installed on the homelab server
- A database to connect to -- either:
  - An existing SQL Server database already created via SQL Server
    Management Studio, reachable from the server (default setup), **or**
  - Nothing extra -- if using the Postgres alternative, Docker Compose
    creates and manages the database for you (see Section 2)
- (Optional, for Google Drive sync) A Google account with a Drive folder
  containing your receipt files

---

## 2. Database options

### Option A: External SQL Server (default)

This is what the root-level `Dockerfile`, `docker-compose.yml`,
`requirements.txt`, and `.env.example` are set up for. Continue to
Section 3 below.

### Option B: Postgres inside Docker (no external database needed)

A `With Postgres` folder in this repo contains 4 files that replace their
root-level equivalents:

```
With Postgres/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

What's different with this option:

- `docker-compose.yml` defines two services instead of one: `db`
  (Postgres 16) and `receipt-analyser` (the app). Postgres's data is
  stored in a named Docker volume, so it persists across container
  restarts independently of the containers themselves.
- `requirements.txt` uses `psycopg2-binary` instead of `pyodbc`.
- `Dockerfile` is simpler -- the entire SQL Server ODBC driver
  installation block is removed, since Postgres doesn't need it.
- `.env.example` uses a Postgres-style connection string:
  ```
  DATABASE_URL=postgresql+psycopg2://receiptapp:YOUR_PASSWORD@db:5432/receiptanalyser
  ```
  `db` is the Postgres service name in `docker-compose.yml` -- Docker's
  internal networking resolves it automatically, no IP address or
  externally reachable database needed.

**To use this option:** copy the 4 files out of `With Postgres/` into the
project root, overwriting the SQL Server versions, then continue with the
rest of this README as normal -- steps 3.3 onward, and Sections 4-8, work
identically regardless of which database you chose. Only `.env`'s
`DATABASE_URL` format and the two database-specific files listed above
differ between the options.

**Nothing in `app.py`, `models.py`, or the Alembic migrations needs to
change either way** -- they talk to the database through SQLAlchemy's
abstraction layer, not raw SQL Server or Postgres syntax, so they don't
know or care which engine is actually underneath.

---

## 3. One-time setup on the homelab server

### 3.1 Get the project onto the server

SSH into the server first:

```bash
ssh <username>@<ip_address>
```

Then copy the project folder over (e.g. via `scp`/WinSCP from Windows), or
clone it from your `thejijogeorge` GitHub repo:

```bash
mkdir -p ~/dockers
cd ~/dockers
git clone https://github.com/thejijogeorge/receipt-analyser.git
cd receipt-analyser
```

If using the Postgres option, copy the 4 files from `With Postgres/` into
the project root now (see Section 2).

### 3.2 Configure the database connection

Copy the example env file and fill in your real values:

```bash
cp .env.example .env
nano .env
```

**If using SQL Server (default `.env.example`):**

```
DATABASE_URL=mssql+pyodbc://sa:YOUR_URL_ENCODED_PASSWORD@192.168.50.58:1433/ExpenseAnalyser?driver=ODBC+Driver+17+for+SQL+Server
```

**Important:** if your password contains special characters (`@`, `:`, `/`,
`#`, `?`, `%`), they must be URL-encoded or the connection string will be
parsed incorrectly. Common ones:

| Character | Encoded |
|-----------|---------|
| `@`       | `%40`   |
| `:`       | `%3A`   |
| `/`       | `%2F`   |
| `#`       | `%23`   |

**If using Postgres (`.env.example` from `With Postgres/`):**

```
POSTGRES_USER=receiptapp
POSTGRES_PASSWORD=YOUR_PASSWORD
POSTGRES_DB=receiptanalyser
DATABASE_URL=postgresql+psycopg2://receiptapp:YOUR_PASSWORD@db:5432/receiptanalyser
```

Note `POSTGRES_PASSWORD` and the password inside `DATABASE_URL` must
match -- the former initializes the Postgres container, the latter is
what the app uses to connect to it.

### 3.3 Set up the receipts folder

This is where receipt files (PDF, JPG, PNG) need to live for the app to
find them — either dropped in manually, or synced there automatically
from Google Drive (see below).

```bash
mkdir -p ~/receipt-analyser/receipts
```

Confirm it's there and currently empty:

```bash
ls ~/receipt-analyser/receipts
```

### 3.4 (Optional) Set up Google Drive sync

If you want the "Sync from Google Drive & Process" button to work:

1. Install `rclone` on the **host** (not just in the container):
   ```bash
   curl https://rclone.org/install.sh | sudo bash
   ```
2. Run the interactive setup:
   ```bash
   rclone config
   ```
   - `n` for New remote
   - Name it exactly `gdrive` (must match `RCLONE_REMOTE` in
     `docker-compose.yml`)
   - Storage type: `24` / `drive` (Google Drive)
   - `client_id`, `client_secret`, `service_account_file`: leave all
     blank, just press Enter
   - `scope`: `1` (full access)
   - `Edit advanced config?`: `n`
   - **`Use auto config?`: `n`** — the server is headless (no browser),
     so this must be `n`, not the default `y`
   - It'll print an `rclone authorize "drive" "..."` command. Since the
     server has no browser, run that exact command on a machine that
     does (e.g. your Windows PC, using the [Windows rclone download](https://rclone.org/downloads/)):
     ```powershell
     .\rclone.exe authorize "drive" "PASTE_THE_TOKEN_HERE"
     ```
     This opens a browser to sign into Google and authorize. It then
     prints a JSON block — copy that whole block and paste it back into
     the `config_token>` prompt on the server.
   - `Configure this as a Shared Drive?`: `n` (unless it actually is one)
   - `y` to keep the remote
3. Test the connection works before relying on the app button:
   ```bash
   rclone ls gdrive:Receipt_Analyser
   ```
   Replace `Receipt_Analyser` with whatever your actual Drive folder is
   called. This should list the receipt files sitting in that folder. If
   it errors with "didn't find section in config file", the remote name
   doesn't match what's in `docker-compose.yml` -- see 3.5.
4. If your remote/folder name differs from `gdrive:Receipt_Analyser`,
   update the `RCLONE_REMOTE` value in `docker-compose.yml` to match.

### 3.5 Edit `docker-compose.yml` for this server

Update the receipts volume path to the folder you created in step 3.3,
and the rclone config path to your actual home directory:

```yaml
volumes:
  - /home/YOUR_USERNAME/receipt-analyser/receipts:/receipts
  - /home/YOUR_USERNAME/.config/rclone:/root/.config/rclone:ro
```

**Use the full explicit path, not `~`.** If `docker compose` ever gets
run with `sudo`, `~` can silently resolve to `/root` instead of your
actual home directory, mounting an empty/nonexistent folder and causing
`rclone sync` to fail with "didn't find section in config file". If your
user is in the `docker` group, you shouldn't need `sudo` at all --
`docker ps` should work without it once you're in that group.

---

## 4. Build and run

**Option A -- build the image on the server** (works from source, no
Docker Hub push needed first):

```bash
docker compose up -d --build
```

First build takes a few minutes (installing tesseract-ocr and rclone
inside the image -- plus the SQL Server ODBC driver, if using that
option).

**Option B -- pull the pre-built image instead** (faster, if you've
already pushed it from Windows via `docker push thejijogeorge/receipt-analyser:latest`):

Remove or comment out the `build: .` line in `docker-compose.yml`, then:

```bash
docker compose pull
docker compose up -d
```

Either way, watch the logs to confirm a clean start:

```bash
docker compose logs -f
```

You should see: database connection succeed → Alembic migrations run →
Flask server starts. Then open:

```
http://<server_ip>:5050
```

---

## 5. Using the app

- **Process from a folder**: enter `/receipts` (the in-container path) and
  hit Process. It reads every PDF, JPG, and PNG in that folder.
- **Sync from Google Drive & Process**: pulls new files from your Drive
  folder into `/receipts` first, then processes them — same result, no
  manual copying needed. Only downloads/processes, doesn't run on a
  schedule -- you have to click it each time.
- **Confirm item names**: after processing, each item shows an editable
  name field. Leave blank to keep the receipt's raw name, or type a
  cleaner name — this applies to every past and future row with that same
  raw item name, not just the one you're looking at. Useful for cleaning
  up noisy OCR text on photographed receipts (e.g. Ambeys).
- **New gift card detected**: some stores (e.g. Kmart) only print the
  amount redeemed, not the remaining balance. The first time such a card
  is seen, enter its balance before that transaction once -- the app
  tracks the running balance itself from then on.
- **Name unrecognized store(s)**: a receipt from a store the parser
  doesn't recognize still gets saved (with no items, since guessing at an
  unknown format risks bad data) and shows up here for naming. The name
  applies to every receipt sharing that same detected store.
- **Item Analytics and Gift Cards are per-store**: from the home page,
  each confirmed store links to its own `/analytics/<store_key>` and
  `/giftcards/<store_key>` pages.

Re-running Process or Sync on the same files is safe — already-processed
receipts (matched by filename) are skipped, not duplicated.

---

## 6. Updating the app after code changes

```bash
docker compose down
docker compose up -d --build
```

Alembic migrations run automatically on every container start, so any new
DB schema changes apply themselves — no manual SQL needed.

---

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Login timeout expired` / `server not found` | (SQL Server) Wrong port syntax — use `:1433` not `,1433` in `DATABASE_URL` |
| `Cannot open database "X" requested by the login` | `.env`'s `DATABASE_URL` still points at the old DB name after a rename — update it to match |
| `Invalid object name 'receipts'` | Migrations haven't run — check `docker compose logs` for Alembic errors, or the container never started |
| Connection works in SSMS but not from the app | (SQL Server) Password has an unencoded special character (see table in 3.2) |
| "Folder not found" | You're using a Windows-style path where a container path (`/receipts`) is expected, or the volume isn't mounted |
| `apt-key: not found` / GPG signature errors during build | (SQL Server option only) Base image drifted to a newer Debian release — `Dockerfile` pins `python:3.12-slim-bookworm` explicitly to avoid this; don't change it back to the floating `python:3.12-slim` tag |
| `None of the supported tools for extracting zip archives were found` during build | Missing `unzip`, needed by rclone's install script — already added to the Dockerfile's package list |
| `rclone sync failed: ... didn't find section in config file ("gdrive")` | The rclone config volume mount used `~` which resolved to the wrong home directory (e.g. `/root` under `sudo`) — use the full explicit path instead, e.g. `/home/YOUR_USERNAME/.config/rclone:/root/.config/rclone:ro` |
| Container name conflict on `docker compose up` | A stale container from a previous run still holds that name — `docker rm -f <name>` first |
| (Postgres) App container exits immediately or can't connect to `db` | Check `POSTGRES_PASSWORD` in `.env` matches the password inside `DATABASE_URL` exactly, and that both files came from the `With Postgres/` folder, not mixed with the SQL Server versions |
| Gift card balance shows for a declined transaction | Shouldn't happen — declined attempts are filtered out during parsing; report the receipt if you see this |
| Item names look garbled on a photographed receipt | Expected — OCR isn't perfect on phone photos. Prices/quantities are still accurate; use "Confirm item names" to clean up the display name once |

---

## 8. Project structure

```
receipt_analyser/
├── app.py                    # Flask routes (process, sync, analytics, gift cards)
├── models.py                 # SQLAlchemy models
├── extractors/                # raw text extraction, by file type
│   ├── pdf_extractor.py        # pdfplumber
│   └── image_extractor.py       # OCR (pytesseract) for photographed/scanned receipts
├── parsers/                   # store-specific parsing, one module per store
│   ├── coles.py
│   ├── woolworths.py
│   ├── jbhifi.py
│   ├── kmart.py
│   ├── ambeys.py
│   ├── unknown.py              # fallback for unrecognized store formats
│   └── utils.py                 # shared helpers (e.g. dash-delimited block splitting)
├── alembic/                    # DB migrations
├── templates/                   # HTML/HTMX pages
├── With Postgres/                # drop-in replacements for a Dockerized Postgres DB
│   ├── Dockerfile                  # instead of the SQL Server ODBC setup
│   ├── docker-compose.yml           # adds a "db" (Postgres) service
│   ├── requirements.txt              # psycopg2-binary instead of pyodbc
│   └── .env.example                   # Postgres-style DATABASE_URL
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh                # wait-for-db + migrate + run
└── requirements.txt
```

Adding a new store is just: write `parsers/newstore.py` with `matches(text)`
and `parse(text)` functions, register it in `parsers/__init__.py`'s
`STORE_MODULES` list. Nothing else needs to change.