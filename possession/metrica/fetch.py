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

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path

import games  # repo-root module, stdlib only; frozen

COMMIT = "e706dd506b360d69d9d123d5b8026e7294b13996"
RAW_URL = "https://raw.githubusercontent.com/metrica-sports/sample-data/{commit}/{path}"

# Repo-relative paths per game, as listed by the GitHub tree API at COMMIT.
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
# Verified on every fetch; `fetch(write_manifest=True)` regenerates it from the local files when the pin moves.
MANIFEST = Path(__file__).with_name("manifest.json")


def data_dir_default() -> Path:
    """games.DATA_DIR / "metrica_sample". Honours MTAH_DATA_DIR like every other asset path."""
    return Path(games.DATA_DIR) / "metrica_sample"


def paths(game: int, data_dir: str | Path | None = None) -> dict[str, Path]:
    """Local paths for one game, like games.require: raises ONE IOError naming every missing file
    plus the exact command to run (`python -m possession fetch-metrica`). Existence only, no hashing
    (hashing 183 MB on every load would be the wrong cost); `fetch` is where bytes are verified."""
    root = _root(data_dir)
    found = {role: _local(root, rel) for role, rel in FILES[game].items()}
    missing = [str(path) for path in found.values() if not path.is_file()]
    if missing:
        raise IOError("Metrica sample data not found:\n  {}\n\nRun `python -m possession fetch-metrica` "
                      "(about 183 MB into {}).".format("\n  ".join(missing), root))
    return found


def fetch(data_dir: str | Path | None = None, *, write_manifest: bool = False) -> list[Path]:
    """Download every file in FILES into data_dir, verified. Returns the local paths.

    Per file: skip if present and sha256 matches the manifest; else GET RAW_URL, stream to a temp
    file while hashing, compare, rename. A manifest mismatch deletes the temp file and raises with
    both digests. With write_manifest=True the digests are recorded instead of compared (local
    files are hashed, missing ones downloaded). ~183 MB total.
    """
    root = _root(data_dir)
    expected = {} if write_manifest else _read_manifest()
    recorded: dict[str, dict[str, object]] = {}
    local = []
    for files in FILES.values():
        for rel in files.values():
            dest = _local(root, rel)
            want = None if write_manifest else expected[rel]["sha256"]
            recorded[rel] = _ensure(rel, dest, want)
            local.append(dest)
    if write_manifest:
        _write_manifest(recorded)
    return local


def _root(data_dir: str | Path | None) -> Path:
    return data_dir_default() if data_dir is None else Path(data_dir)


def _local(root: Path, rel: str) -> Path:
    return root / Path(rel).relative_to("data")


def _read_manifest() -> dict[str, dict[str, object]]:
    manifest = json.loads(MANIFEST.read_text())
    if manifest["commit"] != COMMIT:
        raise ValueError(f"{MANIFEST.name} pins {manifest['commit']}, fetch.py pins {COMMIT}")
    files = manifest["files"]
    unlisted = [rel for group in FILES.values() for rel in group.values() if rel not in files]
    if unlisted:
        raise ValueError(f"{MANIFEST.name} has no digest for: {unlisted}")
    return files


def _write_manifest(files: dict[str, dict[str, object]]) -> None:
    tmp = MANIFEST.with_name(MANIFEST.name + ".part")
    tmp.write_text(json.dumps({"commit": COMMIT, "files": files}, indent=2) + "\n")
    os.replace(tmp, MANIFEST)


def _hash_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _ensure(rel: str, dest: Path, want: str | None) -> dict[str, object]:
    """Leave `dest` holding the bytes whose sha256 is `want` (any bytes if None); return its manifest entry."""
    if dest.is_file():
        have, size = _hash_file(dest)
        if want is None or have == want:
            print(f"ok       {rel}")
            return {"sha256": have, "bytes": size}
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")
    tmp = Path(tmp_name)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(RAW_URL.format(commit=COMMIT, path=rel), timeout=60) as resp:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if want is not None and digest.hexdigest() != want:
            raise ValueError(f"{rel}: downloaded sha256 {digest.hexdigest()}, manifest says {want}")
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    print(f"fetched  {rel}  {size:,} bytes")
    return {"sha256": digest.hexdigest(), "bytes": size}
