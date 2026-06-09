# Nasazení — evidence.spznaklic.cz

Runbook pro nasazení **Úkony Trackeru** jako hostovaného webu na stejném stacku
jako `zadosti.spznaklic.cz` / `hunter.spznaklic.cz`.

> **Pojmenování:** identita aplikace = **`ukony`** (kontejner `ukony-app`, image
> `ukony`, cesty `/share/Container/ukony/...`); veřejná subdoména =
> **`evidence.spznaklic.cz`**. Interní port **8090** (hunter 8088, zadosti 8089).

Stack: **Cloudflare Tunnel → sdílený nginx (docker síť `spznaklic-web_default`) →
gunicorn kontejner**. TLS ukončuje Cloudflare; nginx i appka přeposílají
`X-Forwarded-*` (Flask je obaluje `ProxyFix`). Data leží na bind-mountu `/data`.

---

## 0. Co je v balíčku (v repu)

| Soubor | Účel |
|---|---|
| `Dockerfile` | dvoustupňový build na `python:3.12-slim`, gunicorn |
| `docker/entrypoint.sh` | chmod `/data` + gunicorn (`app:application`), **1 worker** (SQLite) |
| `docker-compose.nas.yml` | služba `ukony` → kontejner `ukony-app` na síti `spznaklic-web_default` |
| `docker/nginx-evidence.conf` | server blok `evidence.spznaklic.cz` → `ukony-app:8090` |
| `.env.example` | šablona pro tajné údaje (NIKDY necommitovat reálné hodnoty) |
| `data/tracker.db` | naseedovaná DB (květen 2026 = 90 úkonů / 145 700 Kč) — gitignored artefakt |

---

## 1. Příprava adresářů na NASu

```bash
mkdir -p /share/Container/ukony/source
mkdir -p /share/Container/ukony/data
```

## 2. Nahrání zdrojů + dat

Zkopíruj na NAS do `/share/Container/ukony/source` tyto položky z `ukony_tracker/`:

```
app.py  config.py  db.py  requirements.txt  Dockerfile
repositories/  services/  routes/  templates/  static/  docker/
```

(Nemusíš kopírovat `tests/`, `scripts/`, `docs/`, `.venv/`, `data/` — image je
nepotřebuje.)

Zkopíruj naseedovanou DB na bind-mount:

```
ukony_tracker/data/tracker.db   →   /share/Container/ukony/data/tracker.db
```

Zkopíruj `docker-compose.nas.yml` do `/share/Container/ukony/`.

## 3. Tajné údaje (`.env`)

Vytvoř `/share/Container/ukony/.env` (mimo git!). Vzor je v `.env.example`:

```
ADMIN_PASSWORD=<jednoduché heslo, které jsi zvolil>
SECRET_KEY=<dlouhý náhodný řetězec>
```

`SECRET_KEY` vygeneruj např.:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> `ADMIN_PASSWORD` zapíná přihlašovací bránu. Když je nastavené, web vyžaduje
> heslo (kromě `/healthz`). Lokální běh bez `.env` zůstává bez přihlášení.

## 4. Build + spuštění (na NASu)

```bash
cd /share/Container/ukony
docker compose -f docker-compose.nas.yml build --no-cache --pull
docker compose -f docker-compose.nas.yml up -d
docker logs -f ukony-app      # gunicorn naslouchá na 8090, healthcheck zelený
```

> Při budoucí aktualizaci zdrojů zvyš `ARG CACHEBUST=...` v `Dockerfile`
> (QNAP SMB snapshot umí držet starou vrstvu), pak `build` + `up -d`.

## 5. nginx

Připoj obsah `docker/nginx-evidence.conf` k **konci** sdíleného configu
`/share/Container/spznaklic/nginx-conf/default.conf` (vedle wordpress, tr212,
hunter, zadosti — nic nepřeskupuj). Pak:

```bash
docker ps --format '{{.Names}}' | grep -i nginx       # zjisti jméno kontejneru
docker exec <nginx-container> nginx -t                 # validace
docker exec <nginx-container> nginx -s reload          # reload
```

## 6. Cloudflare Tunnel + DNS

V Cloudflare → **Zero Trust → Networks → Tunnels** přidej do existujícího
tunelu *Published application route*:

```
Hostname:  evidence.spznaklic.cz
Service:   http://<nginx-origin>      (stejný origin jako hunter / zadosti)
```

Cloudflare pro tunelové routy vytvoří DNS záznam automaticky. (Host hlavička
`evidence.spznaklic.cz` vybere správný nginx server blok.)

## 7. Ověření

Otevři **https://evidence.spznaklic.cz** → přihlašovací stránka → zadej heslo →
Přehled s naseedovanými květnovými daty (90 úkonů / 145 700 Kč).

```bash
# z NASu lokálně bez Cloudflare:
docker exec ukony-app python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8090/healthz').read())"
```

---

## Poznámky

- **SQLite ⇒ 1 gunicorn worker.** Více procesů by se pralo o zámek DB; vlákna
  (`--threads 4`) zvládnou souběh pro jednoho uživatele.
- **Zálohy** se dělají automaticky před každým zápisem (throttle 5 min) do
  `/data/backups/`. Drží se posledních 30.
- **`POST /api/ukony`** je zatím za přihlašovací bránou. Až se bude napojovat
  Přepis (žádosti) appka, přidej API klíč (server-to-server volání nemá session).
- Změna hesla = úprava `ADMIN_PASSWORD` v `.env` na NASu + `docker compose up -d`.
