# AGENTS.md

deciframe is a song-discovery tool for musicians: search by title/artist,
genre, chords you already know, or a famous chord sequence, and it finds
similar songs. Full description: [README.md](README.md).

## Stack

- Backend: Python 3.9, Flask 3.1, gunicorn. `main.py` owns the routes and loads
  `data/top/dataset_final.csv` into memory once at startup. Songs and genres are
  still CSV-backed and in memory; the sequence catalog lives in SQLite through
  `sequencias_store.py`, and `matching.py` holds the in-memory bitset index.
- Frontend: AngularJS 1.4.9 + jQuery, loaded from CDN in `static/index.html`,
  no build step. Legacy, and there's no plan to modernize the stack itself —
  but touching it is no longer off-limits when a task needs it; see
  [docs/adr/0003-lift-frontend-freeze.md](docs/adr/0003-lift-frontend-freeze.md).
- Deploy: local-only via Docker for now. No cloud target has been chosen. The
  app runs with a single gunicorn worker.

## Run locally

Docker (matches how the app actually ships):

```
docker build -t ciframe .
docker run --name deciframe -p 8080:8080 -v deciframe-data:/data ciframe
```

The named volume `deciframe-data` persists the SQLite catalog at
`/data/deciframe.db`. Do not mount a volume at `/app/data`: it would hide the
CSV and break startup.

Or a plain virtualenv:

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py        # serves on :5000 instead of :8080
```

Without `DECIFRAME_DB`, the local catalog is `./var/deciframe.db`; the parent
directory is created automatically. The database is not in the repository and
`var/`, `*.db`, `*.db-wal`, and `*.db-shm` are ignored.

## Verify it's up

```
curl http://localhost:8080/generos
curl http://localhost:8080/sequencias
```

`/generos` should return a JSON array of genre names (e.g.
`["Rock", "Samba", ...]`). `/sequencias` should list at least the 6 seeds with
IDs 0–5. If it hangs on startup, it's still parsing the CSV and computing the
seed bitsets — give it a few seconds.

## Tests

```
python -m unittest discover -s tests -v
```

The regression oracle for the matching rule remains
`artifacts/verifica_matching.py`.

Optional browser smoke test (Selenium + geckodriver + Firefox, not part of the
unittest suite):

```
.venv/bin/pip install selenium
GECKODRIVER=/path/to/geckodriver .venv/bin/python artifacts/smoke_frontend.py
```

## Gotchas

- Editing `data/top/*.csv` requires a restart: it's read once at import time, not per-request.
- Every endpoint returns `json.dumps(...)` as a plain string, not `jsonify` — responses come back `Content-Type: text/html`. This is intentional legacy behavior; changing it is a real API change, not a cleanup.
- Check `docs/adr/` before changing the deploy setup — it has a documented reason for its current state.
- The sequence index, cache and rate limiter are per process. Keep `--workers 1`; `WEB_CONCURRENCY` is not supported.
- The SQLite catalog lives outside `/app` (`/data/deciframe.db` in the image, `./var/deciframe.db` locally). Backups are the operator's responsibility — stop the container or use `VACUUM INTO`.
- Registration is anonymous: 10 `POST /sequencias` per minute per IP, a 500-custom-sequence cap, and a 16 KB request body limit.
