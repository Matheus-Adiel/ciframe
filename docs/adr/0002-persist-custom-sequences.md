# Persist custom chord sequences in SQLite

The sequence catalog used to be six hardcoded entries in `main.py`, with the
corresponding match tags precomputed in `SEQ_FAMOSA` in
`data/top/dataset_final.csv`. That worked while the catalog was fixed, but it
cannot support anonymous visitors registering new sequences: writing new indices
back into the 77 MB CSV would require rewriting the file, restarting the process
to reload it, and would still lose data when the container is recreated. The
feature requires the sequence catalog to survive container restarts and to grow
without a redeploy, while songs and genres stay CSV-backed and in memory.

We decided to introduce a small SQLite database as the sequence catalog. SQLite
is in the Python standard library, so it adds no dependency to the image; it
stores the whole catalog in one file, supports transactions and a unique
constraint for deduplication, and fits the existing single-container, local-only
deploy. The six original sequences are seeded with fixed IDs 0–5 so their
behavior is unchanged; custom sequences get IDs from 6 upward. Each row stores
the ordered chord list as JSON, a normalized key for duplicate detection, the
origin (`original`/`customizada`) and a creation timestamp. There is
deliberately no `nome` column: the chords themselves are the label. The six seeds
are immutable from the API's point of view — there is no update or delete
endpoint, and a registration that duplicates a seed returns the seed row with
HTTP 200.

The database lives outside `/app`, at `DECIFRAME_DB` (default
`/data/deciframe.db` in the image, `./var/deciframe.db` locally). The Dockerfile
creates `/data` and declares it as a volume, and the documented `docker run` uses
a named volume. Mounting a volume at `/app/data` would hide the CSV and break
startup, so that is explicitly avoided. The schema is created idempotently at
startup and versioned with `PRAGMA user_version`; seeds are inserted with
`INSERT OR IGNORE`, so an empty volume bootstraps itself and an existing volume
is not duplicated. The app remains single-worker; `--workers 1` is fixed and
`WEB_CONCURRENCY` is not part of the supported setup.

Matching is not stored in the database. For each sequence, the app computes a
bitset with one bit per song, using the legacy rule: the sequence must appear as
a contiguous block in `musica.cifra`, in the exact order, and every chord in the
song must belong to the sequence's chord set, compared case-insensitively. The
six originals are computed eagerly at startup (about one second) and custom
sequences loaded from the database are computed lazily on their first search,
then cached; a newly registered sequence is computed during the `POST`. This
keeps startup independent of the number of custom sequences and bounds memory:
67,585 songs use 8,449 bytes per sequence, so 500 customs plus the six seeds are
about 4.1 MiB, plus a one-time position map of a few megabytes. The cap of 500
custom sequences keeps the worst case bounded; the measured cost of computing one
sequence is 0.12–0.34 s, so computing all customs eagerly would be a real
startup risk.

Extending the CSV with new `SEQ_FAMOSA` indices was rejected because it rewrites
a 77 MB read-only data file, requires a restart to reload, and still loses data
on container recreation. Computing matches on every request was rejected because
each sequence costs 0.12–0.34 s over 67,585 songs; the bitset cache pays that
once. Materializing the match sets in the database was rejected because it would
write hundreds or thousands of rows per sequence and make the database the hot
path for a read-only query; the in-memory bitset is smaller and faster in the
single-process setup. TinyDB, JSON files and `diskcache` were rejected for weaker transaction
and concurrency semantics, and DuckDB/libSQL/LMDB or an external database were
rejected as unnecessary dependencies or as a violation of the single-container
deploy in ADR 0001.

The trade-offs are deliberate. SQLite is not a multi-writer service, and the
in-memory index and rate limiter are per process; supporting multiple gunicorn
workers would require revisiting both. The catalog is anonymous, so we added a
simple per-IP `POST` limit (10/min), the 500-sequence cap, a 16 KB request-size
limit and idempotent duplicates (HTTP 200 with the existing ID, while a new
registration returns 201) to keep abuse cheap. Because the database is a file on
a volume, backups are the operator's responsibility; `VACUUM INTO` or stopping
the container before copying is the safe path. None of this changes the
CSV-backed song/genre catalog, the existing JSON-over-`json.dumps` response
style, or the local-only Docker deployment from ADR 0001.
