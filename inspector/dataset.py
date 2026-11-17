"""Challenge adapters. Only byte offsets and compact timelines stay in memory."""

from array import array
import csv
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from games import GAME, GAMES, asset_paths, half_video_blocks, require

FPS = GAMES[GAME]["fps"]
FRAMES = GAMES[GAME]["n_video_frames"]
PITCH = dict(zip(("length", "width"), GAMES[GAME]["pitch"]))


def half_blocks(n_frames):
    if n_frames != FRAMES:
        return []
    return [{"name": "First half" if half == 1 else "Second half", "start": start, "end": end + 1}
            for half, start, end in half_video_blocks(GAME)]


def xml_root(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as error:
        raise ValueError(f"{Path(path).name}: invalid XML ({error})") from error
    # Accept both namespaced and plain FIFA/EPTS / SportsCode exports.
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    return root


def finite(value):
    number = float(value)
    if math.isinf(number):
        raise ValueError("infinite values are not supported; missing values must be NaN")
    return None if math.isnan(number) else number


def observation(group):
    fields = group.strip().split(",")
    if len(fields) not in (2, 3):
        raise ValueError("Tracking observations need x,y[,speed]")
    values = [finite(field) for field in fields]
    x, y = values[:2]
    if x is None or y is None:
        return None
    return {"x": x, "y": y, "speed": values[2] if len(values) == 3 else None}


def usable_homography(matrix):
    """Reject rank loss with a relative determinant check, independent of scale."""
    rows = [matrix[index:index + 3] for index in (0, 3, 6)]
    scales = [max(abs(value) for value in row) for row in rows]
    if not all(scales):
        return False
    a, b, c, d, e, f, g, h, i = [value / scale for row, scale in zip(rows, scales) for value in row]
    terms = [a * e * i, b * f * g, c * d * h, -c * e * g, -b * d * i, -a * f * h]
    return abs(math.fsum(terms)) > 32 * math.ulp(1.0) * math.fsum(abs(term) for term in terms)


def runs(values):
    """Half-open intervals; labels may be strings or booleans."""
    result = []
    for frame, label in enumerate(values):
        if not result or result[-1]["label"] != label:
            result.append({"start": frame, "end": frame + 1, "label": label})
        else:
            result[-1]["end"] = frame + 1
    return result


def load_prediction(path, n_frames):
    labels = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        if [x.strip().lower() for x in header] != ["frame", "label"]:
            raise ValueError(f"{Path(path).name}: expected exactly frame,label columns")
        for index, row in enumerate(reader):
            if len(row) != 2 or row[0].strip() != str(index):
                raise ValueError(f"{Path(path).name}: expected frame {index} in order")
            label = row[1].strip().upper()
            if label not in {"H", "A", "D", "X"}:
                raise ValueError(f"{Path(path).name}: invalid or blank label at frame {index}")
            labels.append(label)
    if len(labels) != n_frames:
        raise ValueError(f"{Path(path).name}: {len(labels)} rows; expected {n_frames}")
    return {"name": Path(path).stem, "segments": runs(labels)}


def load_tags(path, fps, n_frames):
    result = []
    for instance in xml_root(path).iter("instance"):
        start = float(instance.findtext("start", "nan"))
        end = float(instance.findtext("end", "nan"))
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("Smart Tagging contains an invalid time interval")
        first, stop = max(0, round(start * fps)), min(n_frames, round(end * fps))
        if stop <= first:
            continue
        result.append({
            "start": first, "end": stop, "code": instance.findtext("code", "Untitled phase"),
            "tags": {label.findtext("group", ""): label.findtext("text", "")
                     for label in instance.findall("label")},
        })
    return sorted(result, key=lambda item: (item["start"], item["end"]))


class MatchDataset:
    def __init__(self, data_dir, predictions=(), video=None, n_frames=FRAMES, fps=FPS):
        self.n_frames, self.fps = n_frames, fps
        bundle = Path(data_dir).expanduser().resolve()
        if bundle.name == "tactical" and not (bundle / "tactical").is_dir():
            bundle = bundle.parent
        paths = {name: Path(path) for name, path in asset_paths(data_dir=bundle).items()}
        try:
            require(("atd_raw", "atd_meta"), data_dir=bundle)
        except OSError as error:
            raise ValueError(str(error)) from error
        self.folder = paths["atd_raw"].parent
        self.raw, meta = paths["atd_raw"], paths["atd_meta"]
        self.homography, tags = paths["homography"], paths["smart_tagging"]
        self.video = Path(video).expanduser().resolve() if video else paths["video"]
        if video and not self.video.is_file():
            raise ValueError("The --video file does not exist")
        if not self.video.is_file():
            self.video = None
        root = xml_root(meta)
        teams = list(root.iter("Team"))
        if (len(teams) != 2 or any(not (team.get("id") or "").strip() for team in teams)
                or len({team.get("id") for team in teams}) != 2):
            raise ValueError("Tracking metadata must contain two distinct teams")
        mapping = {team.get("id"): side for team, side in zip(teams, ("H", "A"))}
        self.teams = {side: team.findtext("Name", side) for team, side in zip(teams, ("H", "A"))}
        self.slots = []
        for player in root.iter("Player"):
            if not (player.get("teamId") or "").strip() or player.get("teamId") not in mapping:
                raise ValueError("Track slot refers to an unknown team")
            self.slots.append(mapping[player.get("teamId")])
        if not self.slots:
            raise ValueError("No track slots found in metadata")
        self.offsets = array("Q")
        visibility = bytearray()
        with self.raw.open("rb") as handle:
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                frame = len(self.offsets)
                try:
                    frame_id, players, ball = line.decode("utf-8").strip().split(":")
                    if int(frame_id) != frame + 1:
                        raise ValueError("frame IDs must be contiguous and start at 1")
                    groups = players.rstrip(";").split(";")
                    if len(groups) != len(self.slots):
                        raise ValueError("track slot count differs from metadata")
                    # Validate each observation once; return only requested windows to the browser.
                    for slot, group in enumerate(groups, 1):
                        try:
                            observation(group)
                        except ValueError as error:
                            raise ValueError(f"track slot {slot}: {error}") from error
                    try:
                        visible = observation(ball) is not None
                    except ValueError as error:
                        raise ValueError(f"ball: {error}") from error
                except (ValueError, UnicodeError) as error:
                    raise ValueError(f"Invalid tracking record {frame + 1}: {error}") from error
                self.offsets.append(offset)
                visibility.append(visible)
        if len(self.offsets) != n_frames:
            raise ValueError(f"Tracking has {len(self.offsets)} frames; expected {n_frames}. "
                             "Use the tactical export; do not pad or trim it.")
        self.visibility = runs(bool(value) for value in visibility)
        self.ball_visible = sum(visibility)
        self.h_offsets = array("Q")
        self.h_columns = []
        if self.homography.is_file():
            self._index_homography()
        self.tags = load_tags(tags, fps, n_frames) if tags.is_file() else []
        if len(predictions) > 8:
            raise ValueError("Load at most eight prediction files at once")
        self.predictions = [load_prediction(path, n_frames) for path in predictions]

    def _index_homography(self):
        required = ["frame", "valid", "reprojection_error"] + [f"h{i}{j}" for i in range(3) for j in range(3)]
        with self.homography.open("rb") as handle:
            self.h_columns = next(csv.reader([handle.readline().decode("utf-8-sig").strip()]))
            if len(set(self.h_columns)) != len(self.h_columns):
                raise ValueError("Homography contains duplicate column names")
            if any(name not in self.h_columns for name in required):
                raise ValueError("Homography is missing required columns")
            while True:
                offset = handle.tell()
                line = handle.readline()
                if not line:
                    break
                frame = len(self.h_offsets)
                try:
                    fields = next(csv.reader([line.decode().strip()]))
                    if len(fields) != len(self.h_columns):
                        raise ValueError("column count differs from header")
                    row = dict(zip(self.h_columns, fields))
                    if int(row["frame"]) != frame:
                        raise ValueError("frame IDs must be contiguous and start at 0")
                    if row["valid"] not in ("0", "1"):
                        raise ValueError("valid must be 0 or 1")
                    matrix = [finite(row[f"h{i}{j}"]) for i in range(3) for j in range(3)]
                    if row["valid"] == "1" and any(value is None for value in matrix):
                        raise ValueError("valid matrix contains missing coordinates")
                    if row["valid"] == "1" and not usable_homography(matrix):
                        raise ValueError("valid matrix is singular or numerically unusable")
                    finite(row["reprojection_error"])
                except (ValueError, KeyError) as error:
                    raise ValueError(f"Invalid homography row {frame}: {error}") from error
                self.h_offsets.append(offset)
        if len(self.h_offsets) != self.n_frames:
            raise ValueError("Homography frame count differs from tracking")

    def frames(self, start, count):
        result = []
        with self.raw.open("rb") as raw:
            raw.seek(self.offsets[start])
            for frame in range(start, min(start + count, self.n_frames)):
                _, groups, ball = raw.readline().decode().strip().split(":")
                players = []
                for index, group in enumerate(groups.rstrip(";").split(";")):
                    point = observation(group)
                    if point is not None:
                        players.append({"slot": index + 1, "team": self.slots[index], **point})
                result.append({"frame": frame, "players": players, "ball": observation(ball),
                               "homography": None, "reprojection_error": None})
        if self.h_offsets:
            with self.homography.open("rb") as handle:
                handle.seek(self.h_offsets[start])
                for item in result:
                    row = dict(zip(self.h_columns, next(csv.reader([handle.readline().decode().strip()]))))
                    if row["valid"] == "1":
                        item["homography"] = [finite(row[f"h{i}{j}"]) for i in range(3) for j in range(3)]
                    item["reprojection_error"] = finite(row["reprojection_error"])
        return result

    def manifest(self):
        return {
            "demo": False, "title": f"{self.teams['H']} × {self.teams['A']}", "fps": self.fps,
            "n_frames": self.n_frames, "pitch": PITCH, "teams": self.teams,
            "track_slots": len(self.slots), "video_url": "/video" if self.video else None,
            "has_homography": bool(self.h_offsets), "tags": self.tags,
            "predictions": self.predictions, "visibility": self.visibility,
            "ball_visible": self.ball_visible,
            "half_blocks": half_blocks(self.n_frames),
        }


class PredictionDataset:
    """Inspect supplied predictions without inventing match observations."""
    def __init__(self, predictions, video=None, n_frames=FRAMES, fps=FPS):
        if not 1 <= len(predictions) <= 8:
            raise ValueError("Prediction-only inspection needs one to eight --prediction files")
        self.n_frames, self.fps = n_frames, fps
        self.video = Path(video).expanduser().resolve() if video else None
        if self.video and not self.video.is_file():
            raise ValueError("The --video file does not exist")
        self.predictions = [load_prediction(path, n_frames) for path in predictions]

    def manifest(self):
        return {"demo": False, "predictions_only": True, "title": "Prediction timelines",
                "n_frames": self.n_frames, "fps": self.fps, "pitch": PITCH,
                "teams": {"H": "Home (H)", "A": "Away (A)"}, "track_slots": 0,
                "video_url": "/video" if self.video else None, "has_homography": False,
                "tags": [], "visibility": [], "ball_visible": None, "predictions": self.predictions,
                "half_blocks": half_blocks(self.n_frames)}

    def frames(self, start, count):
        return []  # No observations are available in this mode.


class DemoDataset:
    """Generated geometry and labels, never derived from the competition match."""
    n_frames, fps, video = 1800, 25, None

    def __init__(self, video=None):
        self.video = Path(video).expanduser().resolve() if video else None
        if self.video and not self.video.is_file():
            raise ValueError("The --video file does not exist")
        self.visibility = runs(not (260 <= frame < 305 or 850 <= frame < 960 or 1320 <= frame < 1348)
                               for frame in range(self.n_frames))

    def manifest(self):
        def state(frame):
            return "H" if frame < 440 else "D" if frame < 560 else "A" if frame < 1150 else "H"
        primary = [state(frame) for frame in range(self.n_frames)]
        noisy = ["D" if any(r["start"] <= f < r["end"] and not r["label"] for r in self.visibility)
                 else ("A" if f % 160 < 9 and primary[f] == "H" else primary[f])
                 for f in range(self.n_frames)]
        return {
            "demo": True, "title": "Synthetic training ground", "fps": self.fps,
            "n_frames": self.n_frames, "pitch": PITCH, "teams": {"H": "Home", "A": "Away"},
            "track_slots": 22, "video_url": "/video" if self.video else None,
            "has_homography": True, "half_blocks": [], "visibility": self.visibility,
            "ball_visible": sum(r["end"] - r["start"] for r in self.visibility if r["label"]),
            "predictions": [{"name": "demo_temporal", "segments": runs(primary)},
                            {"name": "demo_nearest", "segments": runs(noisy)}],
            "tags": [
                {"start": 0, "end": 260, "code": "BUILD UP", "tags": {"Team": "Home"}},
                {"start": 220, "end": 440, "code": "PROGRESSION", "tags": {"Team": "Home"}},
                {"start": 440, "end": 580, "code": "SET PIECES", "tags": {"Type": "Throw-in", "Team": "N/A"}},
                {"start": 560, "end": 900, "code": "BUILD UP", "tags": {"Team": "Away"}},
                {"start": 880, "end": 1150, "code": "CREATING CHANCES", "tags": {"Team": "Away"}},
                {"start": 1150, "end": 1450, "code": "ATTACKING TRANSITION", "tags": {"Team": "Home"}},
                {"start": 1430, "end": 1800, "code": "BALL IN FINAL THIRD", "tags": {"Team": "Home"}},
            ],
        }

    def frames(self, start, count):
        result = []
        for frame in range(start, min(start + count, self.n_frames)):
            t = frame / self.fps
            players = [{"slot": slot + 1, "team": "H" if slot < 11 else "A",
                        "x": 0.12 + (slot % 6) * .14 + .04 * math.sin(t / 4 + slot),
                        "y": .12 + (slot % 4) * .25 + .035 * math.cos(t / 3 + slot),
                        "speed": 2 + math.sin(t + slot)} for slot in range(22)]
            visible = next(r["label"] for r in self.visibility if r["start"] <= frame < r["end"])
            owner = players[4 if frame < 440 or frame >= 1150 else 15]
            ball = {"x": owner["x"] + .015, "y": owner["y"] + .012, "speed": 4.2} if visible else None
            result.append({"frame": frame, "players": players, "ball": ball,
                           "homography": [1600, 0, 160, 0, 900, 90, 0, 0, 1],
                           "reprojection_error": .25})
        return result
