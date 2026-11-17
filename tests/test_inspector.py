import csv
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json

from inspector.dataset import DemoDataset, MatchDataset, PredictionDataset, load_prediction, load_tags, observation
from inspector.server import make_server


def fixture(root, count=8):
    folder = root / "tactical"
    folder.mkdir()
    (folder / "BAR-ATH_tactical_atd.xml").write_text('''<EPTS xmlns="urn:test">
      <Team id="bar"><Name>Barcelona</Name></Team><Team id="ath"><Name>Athletic Club</Name></Team>
      <Player id="99" teamId="bar"/><Player id="2" teamId="ath"/>
    </EPTS>''')
    lines = []
    for frame in range(count):
        ball = "NaN,NaN,NaN" if frame in (2, 3, 4) else f"{frame / 10},0.5,3"
        away = "NaN,NaN,NaN" if frame == 5 else "0.8,0.4,2"
        lines.append(f"{frame + 1}:0.2,0.3,1;{away}:{ball}\n")
    (folder / "BAR-ATH_tactical_atd.txt").write_text("".join(lines))
    with (folder / "BAR-ATH_tactical_homography.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame"] + [f"h{i}{j}" for i in range(3) for j in range(3)] + ["reprojection_error", "valid"])
        for frame in range(count):
            matrix = [1920, 0, 10, 0, 1080, 20, 0, 0, 1] if frame != 3 else ["NaN"] * 9
            writer.writerow([frame] + matrix + [0.2, 0 if frame == 3 else 1])
    (folder / "BAR-ATH_tactical_smart_tagging.xml").write_text('''<file><ALL_INSTANCES>
      <instance><start>0.04</start><end>0.16</end><code>BUILD UP</code>
      <label><group>Team</group><text>Barcelona</text></label></instance>
      <instance><start>0.28</start><end>2</end><code>SET PIECES</code>
      <label><group>Team</group><text>N/A</text></label></instance>
    </ALL_INSTANCES></file>''')
    prediction = root / "candidate.csv"
    prediction.write_text("frame,label\n" + "".join(f"{f},{'H' if f < 3 else 'D' if f < 5 else 'A'}\n" for f in range(count)))
    return folder, prediction


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder, self.prediction = fixture(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def dataset(self, **kwargs):
        return MatchDataset(self.root, [self.prediction], n_frames=8, **kwargs)

    def test_tracking_alignment_metadata_and_missing_values(self):
        data = self.dataset()
        frames = data.frames(0, 8)
        self.assertEqual([f["frame"] for f in frames], list(range(8)))
        self.assertEqual(frames[0]["ball"]["x"], 0)
        self.assertEqual(frames[7]["ball"]["x"], 0.7)
        self.assertEqual(frames[0]["players"][0], {"slot": 1, "team": "H", "x": .2, "y": .3, "speed": 1})
        self.assertEqual(frames[0]["players"][1]["team"], "A")
        self.assertIsNone(frames[2]["ball"])
        self.assertEqual(len(frames[5]["players"]), 1)
        self.assertEqual(data.frames(7, 125), [frames[7]])
        self.assertEqual(data.ball_visible, 5)
        self.assertEqual(data.visibility[1], {"start": 2, "end": 5, "label": False})
        json.dumps(frames, allow_nan=False)

    def test_homography_validity_and_normalized_coordinates(self):
        frames = self.dataset().frames(2, 3)
        self.assertEqual(frames[0]["homography"], [1920, 0, 10, 0, 1080, 20, 0, 0, 1])
        self.assertIsNone(frames[1]["homography"])
        self.assertEqual(frames[0]["players"][0]["x"], .2)

    def test_tag_time_base_half_open_end_and_clip(self):
        tags = self.dataset().tags
        self.assertEqual((tags[0]["start"], tags[0]["end"]), (1, 4))
        self.assertEqual(tags[0]["tags"]["Team"], "Barcelona")
        self.assertEqual((tags[1]["start"], tags[1]["end"]), (7, 8))
        self.assertEqual(tags[1]["tags"]["Team"], "N/A")

    def test_prediction_segments_and_normalization(self):
        prediction = load_prediction(self.prediction, 8)
        self.assertEqual(prediction["segments"], [
            {"start": 0, "end": 3, "label": "H"}, {"start": 3, "end": 5, "label": "D"},
            {"start": 5, "end": 8, "label": "A"}])
        self.prediction.write_text(" FRAME , LABEL \n0, h \n1,X\n")
        self.assertEqual(load_prediction(self.prediction, 2)["segments"][0]["label"], "H")

    def test_predictions_only_preserves_labels_without_fabricated_observations(self):
        data = PredictionDataset([self.prediction], n_frames=8)
        manifest = data.manifest()
        self.assertTrue(manifest["predictions_only"])
        self.assertFalse(manifest["demo"])
        self.assertEqual(manifest["visibility"], [])
        self.assertIsNone(manifest["ball_visible"])
        self.assertEqual(data.frames(0, 8), [])
        self.assertEqual(manifest["predictions"][0]["segments"][1]["label"], "D")
        for paths in ([], [self.prediction] * 9):
            with self.assertRaises(ValueError):
                PredictionDataset(paths, n_frames=8)

    def test_prediction_rejects_misalignment_blank_and_wrong_length(self):
        for content in ("frame,label\n1,H\n", "frame,label\n0,H\n0,A\n",
                        "frame,label\n0,\n", "frame,label\n0,Z\n", "frame,label,extra\n0,H,x\n"):
            with self.subTest(content=content):
                self.prediction.write_text(content)
                with self.assertRaises(ValueError):
                    load_prediction(self.prediction, 1)
        self.prediction.write_text("frame,label\n0,H\n")
        with self.assertRaisesRegex(ValueError, "expected 8"):
            load_prediction(self.prediction, 8)

    def test_interior_tracking_id_error_is_rejected(self):
        path = self.folder / "BAR-ATH_tactical_atd.txt"
        path.write_text(path.read_text().replace("4:", "3:"))
        with self.assertRaisesRegex(ValueError, "contiguous"):
            self.dataset()

    def test_wrong_frame_count_and_slot_count_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected 199319"):
            MatchDataset(self.root)
        path = self.folder / "BAR-ATH_tactical_atd.txt"
        path.write_text(path.read_text().replace(";0.8,0.4,2", ""))
        with self.assertRaisesRegex(ValueError, "slot count"):
            self.dataset()

    def test_optional_assets_and_direct_tactical_folder(self):
        for name in ("BAR-ATH_tactical_homography.csv", "BAR-ATH_tactical_smart_tagging.xml"):
            (self.folder / name).unlink()
        data = MatchDataset(self.folder, n_frames=8)
        self.assertEqual(data.tags, [])
        self.assertIsNone(data.frames(0, 1)[0]["homography"])
        self.assertIsNone(data.manifest()["video_url"])
        self.assertFalse(data.manifest()["demo"])

    def test_homography_gap_and_invalid_matrix_rejected(self):
        path = self.folder / "BAR-ATH_tactical_homography.csv"
        original = path.read_text()
        path.write_text(original.replace("2,1920", "7,1920"))
        with self.assertRaisesRegex(ValueError, "contiguous"):
            self.dataset()
        path.write_text(original.replace("0,1920,", "0,NaN,"))
        with self.assertRaisesRegex(ValueError, "valid matrix"):
            self.dataset()

    def test_demo_is_synthetic_and_has_gap_boundaries(self):
        data = DemoDataset()
        self.assertTrue(data.manifest()["demo"])
        self.assertIsNotNone(data.frames(259, 1)[0]["ball"])
        self.assertIsNone(data.frames(260, 1)[0]["ball"])
        self.assertIsNotNone(data.frames(305, 1)[0]["ball"])

    def test_corrupt_observations_rejected_before_missingness(self):
        for value in ("0.2,0.3,1,UNEXPECTED", "NaN,NaN,INVALID", "inf,0.3,1", "NaN,NaN,-inf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                observation(value)
        self.assertIsNone(observation("NaN,NaN,NaN"))
        self.assertEqual(observation("0.2,0.3")["speed"], None)
        path = self.folder / "BAR-ATH_tactical_atd.txt"
        path.write_text(path.read_text().replace("0.2,0.3,1", "0.2,0.3,inf", 1))
        with self.assertRaisesRegex(ValueError, "record 1: track slot 1"):
            self.dataset()

    def test_malformed_xml_has_contextual_value_error(self):
        for filename in ("BAR-ATH_tactical_atd.xml", "BAR-ATH_tactical_smart_tagging.xml"):
            path = self.folder / filename
            original = path.read_text()
            path.write_text("<EPTS><Team>")
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, filename + ": invalid XML"):
                self.dataset()
            path.write_text(original)

    def test_absent_team_identifiers_cannot_invent_home_membership(self):
        path = self.folder / "BAR-ATH_tactical_atd.xml"
        original = path.read_text()
        for bad in (original.replace('id="bar"', ''), original.replace('id="bar"', 'id=" "'),
                    original.replace('teamId="bar"', '')):
            with self.subTest(bad=bad):
                path.write_text(bad)
                with self.assertRaises(ValueError):
                    self.dataset()

    def test_ambiguous_homography_structure_rejected(self):
        path = self.folder / "BAR-ATH_tactical_homography.csv"
        original = list(csv.reader(path.read_text().splitlines()))
        for rows in ([original[0] + ["h00"]] + [row + ["5"] for row in original[1:]],
                     [original[0], original[1] + ["extra"]] + original[2:],
                     [original[0], original[1][:-1]] + original[2:]):
            with self.subTest(rows=rows[:2]):
                with path.open("w", newline="") as handle:
                    csv.writer(handle).writerows(rows)
                with self.assertRaisesRegex(ValueError, "duplicate|row 0: column count"):
                    self.dataset()

    def test_singular_calibration_rejected_and_scaled_calibration_preserved(self):
        path = self.folder / "BAR-ATH_tactical_homography.csv"
        original = list(csv.reader(path.read_text().splitlines()))
        for matrix in ([0] * 9, [0, 0, 40, 0, 0, 60, 0, 0, 1]):
            rows = [row[:] for row in original]
            rows[1][1:10] = matrix
            with path.open("w", newline="") as handle:
                csv.writer(handle).writerows(rows)
            with self.subTest(matrix=matrix), self.assertRaisesRegex(ValueError, "singular"):
                self.dataset()
        for scale in (1e-200, 1e200, -7):
            rows = [row[:] for row in original]
            rows[1][1:10] = [float(value) * scale for value in original[1][1:10]]
            with path.open("w", newline="") as handle:
                csv.writer(handle).writerows(rows)
            self.assertIsNotNone(self.dataset().frames(0, 1)[0]["homography"])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.video = Path(cls.temp.name) / "synthetic.mp4"
        cls.video.write_bytes(bytes(range(256)) * 4)
        cls.server = make_server(DemoDataset(cls.video), 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def get(self, path, headers=None, method="GET"):
        return urlopen(Request(self.base + path, headers=headers or {}, method=method), timeout=5)

    def test_manifest_frame_chunk_and_static_assets(self):
        with self.get("/api/manifest") as response:
            self.assertTrue(json.load(response)["demo"])
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with self.get("/api/frames?start=1799&count=125") as response:
            self.assertEqual(len(json.load(response)["frames"]), 1)
        for path in ("/", "/app.js", "/core.mjs", "/styles.css"):
            with self.subTest(path=path), self.get(path) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 100)

    def test_ranges_and_head_for_video_seeking(self):
        for header, start, end in (("bytes=10-19", 10, 19), ("bytes=1000-", 1000, 1023),
                                   ("bytes=-8", 1016, 1023), ("bytes=1000-9999", 1000, 1023)):
            with self.subTest(header=header), self.get("/video", {"Range": header}) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.headers["Content-Range"], f"bytes {start}-{end}/1024")
                self.assertEqual(response.read(), self.video.read_bytes()[start:end + 1])
        with self.get("/video", method="HEAD") as response:
            self.assertEqual(response.headers["Content-Length"], "1024")
            self.assertEqual(response.read(), b"")

    def test_bad_video_ranges(self):
        for header in ("bytes=1024-", "bytes=-0", "bytes=20-10", "bytes=0-1,4-5", "bytes=-"):
            with self.subTest(header=header), self.assertRaises(HTTPError) as error:
                self.get("/video", {"Range": header})
            self.assertEqual(error.exception.code, 416)
            self.assertEqual(error.exception.headers["Content-Range"], "bytes */1024")
            error.exception.close()

    def test_invalid_chunks_paths_host_and_origin(self):
        cases = [("/api/frames?start=-1", {}, 400), ("/api/frames?start=1800", {}, 400),
                 ("/api/frames?count=251", {}, 400), ("/api/frames?count=0", {}, 400),
                 ("/api/frames?start=abc", {}, 400), ("/../CHALLENGE_NOTES.md", {}, 404),
                 ("/api/manifest", {"Host": "attacker.example"}, 403),
                 ("/api/manifest", {"Origin": "https://attacker.example"}, 403)]
        for path, headers, code in cases:
            with self.subTest(path=path, headers=headers), self.assertRaises(HTTPError) as error:
                self.get(path, headers)
            self.assertEqual(error.exception.code, code)
            error.exception.close()


if __name__ == "__main__":
    unittest.main()
