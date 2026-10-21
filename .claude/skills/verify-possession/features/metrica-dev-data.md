# Prepare the Metrica dev data

`fetch-metrica` downloads Metrica Sports' public sample games at a pinned commit and checks each file against the committed sha256 manifest. `python -m possession.metrica` then parses the games and prints acceptance tables for the event-derived labels, which the dev worlds are built from.

## Sub-features

- `metrica-fetch` downloads missing files and verifies all 9 files.
- `metrica-tables` prints the per-game table and the pooled spell table per label rule.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession fetch-metrica [--data-dir DIR]`.
- Run `.venv/bin/python -m possession.metrica [--data-dir DIR]`.

## Driving it with run.sh

Preconditions:

- The doctor prints no `FAIL` line.
- For a fresh download, network access to GitHub is available. With all 9 files already present, `fetch-metrica` only verifies them.

- **Verify files.** Run `$V/run.sh "$RUN_ID" fetch .venv/bin/python -m possession fetch-metrica`. Exit code is `0`. stdout has one `ok` line per file and ends with `9 files verified`.
- **Tables.** Run `$V/run.sh "$RUN_ID" metrica .venv/bin/python -m possession.metrica`. Exit code is `0`. The per-game table shows a `pooled` row with spells `1073`, `978`, `825` and `721` for merges of 0, 1, 2 and 3 s, and `no` under ball NaN. The pooled spell table shows `h3p3` with `709` spells, mean `14.7` s and median `10.3` s.

## Gotchas

- The download is about 183 MB. It goes to `$MTAH_DATA_DIR/metrica_sample` (default `data/metrica_sample`), which is gitignored. Never commit it.
- `--write-manifest` regenerates the committed manifest from local files. Use it only when the pinned commit changes on purpose.
- The `parse s` column is wall-clock time. It differs between runs, so leave it out of comparisons.
- Metrica asks for acknowledgement. The technical document must credit Metrica Sports for the sample data.
