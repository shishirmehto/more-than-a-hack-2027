"""Write a small synthetic challenge-format bundle for end-to-end browser QA."""

import argparse
import csv
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspector.dataset import DemoDataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New empty output directory")
    args = parser.parse_args()
    root = args.output
    if root.exists() and any(root.iterdir()):
        parser.error("Use a new or empty directory; existing files will not be overwritten")
    folder = root / "tactical"
    folder.mkdir(parents=True, exist_ok=True)
    data = DemoDataset()
    manifest = data.manifest()
    metadata = ET.Element("EPTS")
    for side in ("H", "A"):
        team = ET.SubElement(metadata, "Team", id=side)
        ET.SubElement(team, "Name").text = f"Synthetic {'home' if side == 'H' else 'away'}"
    for slot in range(22):
        ET.SubElement(metadata, "Player", id=str(slot + 1), teamId="H" if slot < 11 else "A")
    ET.ElementTree(metadata).write(folder / "BAR-ATH_tactical_atd.xml", encoding="utf-8")

    def encode(point):
        return ",".join(str(point[key]) for key in ("x", "y", "speed")) if point else "NaN,NaN,NaN"

    with (folder / "BAR-ATH_tactical_atd.txt").open("w") as raw, \
            (folder / "BAR-ATH_tactical_homography.csv").open("w", newline="") as homography:
        writer = csv.writer(homography)
        writer.writerow(["frame"] + [f"h{i}{j}" for i in range(3) for j in range(3)] + ["reprojection_error", "valid"])
        for start in range(0, data.n_frames, 125):
            for frame in data.frames(start, 125):
                raw.write(f"{frame['frame'] + 1}:" + ";".join(encode(p) for p in frame["players"]) + ":" + encode(frame["ball"]) + "\n")
                writer.writerow([frame["frame"]] + frame["homography"] + [frame["reprojection_error"], 1])
    tagging = ET.Element("file")
    for tag in manifest["tags"]:
        instance = ET.SubElement(tagging, "instance")
        for name, value in (("start", tag["start"] / data.fps), ("end", tag["end"] / data.fps), ("code", tag["code"])):
            ET.SubElement(instance, name).text = str(value)
        for group, value in tag["tags"].items():
            label = ET.SubElement(instance, "label")
            ET.SubElement(label, "group").text = group
            ET.SubElement(label, "text").text = value
    ET.ElementTree(tagging).write(folder / "BAR-ATH_tactical_smart_tagging.xml", encoding="utf-8")
    for prediction in manifest["predictions"]:
        with (root / f"{prediction['name']}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["frame", "label"])
            for segment in prediction["segments"]:
                writer.writerows((frame, segment["label"]) for frame in range(segment["start"], segment["end"]))
    print(f"Wrote {data.n_frames} synthetic frames to {root}")


if __name__ == "__main__":
    main()
