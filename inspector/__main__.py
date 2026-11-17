import argparse
import os
from pathlib import Path

from .dataset import DemoDataset, MatchDataset, PredictionDataset, FRAMES, FPS
from .server import make_server
from games import DATA_DIR, asset_paths


def main():
    parser = argparse.ArgumentParser(description="Local, read-only possession inspector")
    parser.add_argument("--data-dir", help="Challenge bundle root or its tactical folder (also MTAH_DATA_DIR)")
    parser.add_argument("--prediction", action="append", default=[], metavar="CSV", help="Repeat to compare up to 8 files")
    parser.add_argument("--video", help="Optional local tactical video path")
    parser.add_argument("--demo", action="store_true", help="Use generated synthetic tracking and labels")
    parser.add_argument("--predictions-only", action="store_true", help="Inspect CSV timelines without tracking files")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--frames", type=int, default=FRAMES, help="Expected tracking rows (default: 199319)")
    parser.add_argument("--fps", type=float, default=FPS, help="Source frame rate (default: 25)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.frames < 1 or not 0 < args.fps <= 240:
        parser.error("Invalid port, frame count, or frame rate")
    configured = args.data_dir or os.environ.get("MTAH_DATA_DIR")
    folder = configured or DATA_DIR
    if args.predictions_only and (args.demo or configured):
        parser.error("--predictions-only cannot be combined with --demo or --data-dir/MTAH_DATA_DIR")
    default_paths = asset_paths(data_dir=folder)
    has_tracking = any(Path(default_paths[name]).exists() for name in ("atd_raw", "atd_meta"))
    demo = not args.predictions_only and (args.demo or (not configured and not has_tracking))
    if demo and args.prediction:
        parser.error("--prediction requires a real --data-dir; demo labels are generated")
    try:
        print("Loading synthetic demo…" if demo else "Loading prediction files…" if args.predictions_only else "Indexing local tactical files…", flush=True)
        if args.predictions_only:
            dataset = PredictionDataset(args.prediction, args.video, args.frames, args.fps)
        else:
            dataset = DemoDataset(args.video) if demo else MatchDataset(folder, args.prediction, args.video, args.frames, args.fps)
        server = make_server(dataset, args.port)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Local inspector: http://127.0.0.1:{server.server_port}", flush=True)
    print("Synthetic data only." if demo else "Match files stay on this machine. Read-only inspection.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
