"""Where the Metrica sample files are, and proof they are the right bytes.

Pinned to commit e706dd506b360d69d9d123d5b8026e7294b13996 of github.com/metrica-sports/sample-data:
raw.githubusercontent.com URLs that name a commit are immutable, so the commit is the pin and the
sha256 manifest is belt and braces (and catches a truncated download). The repo has no LICENSE; its
README asks users to be responsible and to acknowledge the source. The technical document must say
"Metrica Sports public sample data" and link the repo. Raw files are untrusted input: parsed, never
executed, never committed (`data/*` is gitignored).

Idempotent (per make-operations-idempotent): re-running skips files whose sha256 already matches,
re-downloads ones that do not, and never leaves a partial file (temp file in the same directory,
atomic rename). Stdlib only (urllib, hashlib). The only network call in the package, and it sends
nothing out: it is a GET of a public file.
"""
from __future__ import annotations

from pathlib import Path

COMMIT = "e706dd506b360d69d9d123d5b8026e7294b13996"
RAW_URL = "https://raw.githubusercontent.com/metrica-sports/sample-data/{commit}/{path}"

# Repo-relative paths per game. Names below are from memory of the repo layout:
# TODO(implementation, first step): confirm against the tree listing at COMMIT, fail loudly if a name is wrong.
FILES: dict[int, dict[str, str]] = {
    1: {"events": "data/Sample_Game_1/Sample_Game_1_RawEventsData.csv",
        "home": "data/Sample_Game_1/Sample_Game_1_RawTrackingData_Home_Team.csv",
        "away": "data/Sample_Game_1/Sample_Game_1_RawTrackingData_Away_Team.csv"},
    2: {"events": "data/Sample_Game_2/Sample_Game_2_RawEventsData.csv",
        "home": "data/Sample_Game_2/Sample_Game_2_RawTrackingData_Home_Team.csv",
        "away": "data/Sample_Game_2/Sample_Game_2_RawTrackingData_Away_Team.csv"},
    3: {"events": "data/Sample_Game_3/Sample_Game_3_events.json",
        "meta": "data/Sample_Game_3/Sample_Game_3_metadata.xml",
        "tracking": "data/Sample_Game_3/Sample_Game_3_tracking.txt"},
}

# Committed next to this file: {"commit": COMMIT, "files": {path: {"sha256": ..., "bytes": ...}}}.
# Written once by `fetch(write_manifest=True)` (trust on first use, then pinned); verified on every fetch.
MANIFEST = Path(__file__).with_name("manifest.json")


def data_dir_default() -> Path:
    """games.DATA_DIR / "metrica_sample". Honours MTAH_DATA_DIR like every other asset path."""
    raise NotImplementedError


def paths(game: int, data_dir: str | Path | None = None) -> dict[str, Path]:
    """Local paths for one game, like games.require: raises ONE IOError naming every missing file
    plus the exact command to run (`python -m possession fetch-metrica`). Existence only, no hashing
    (hashing 183 MB on every load would be the wrong cost); `fetch` is where bytes are verified."""
    raise NotImplementedError


def fetch(data_dir: str | Path | None = None, *, write_manifest: bool = False) -> list[Path]:
    """Download every file in FILES into data_dir, verified. Returns the local paths.

    Per file: skip if present and sha256 matches the manifest; else GET RAW_URL, stream to a temp
    file while hashing, compare, rename. A manifest mismatch deletes the temp file and raises with
    both digests. With write_manifest=True (first run only) the digests are recorded instead of
    compared. ~183 MB total.
    """
    # TODO: for game, files in FILES.items(): for role, rel in files.items(): _ensure(rel, dest, manifest)
    raise NotImplementedError
