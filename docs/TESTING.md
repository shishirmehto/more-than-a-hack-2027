# Initial verification — 24 October 2026

## Automated checks

- `python3 -m unittest discover -s tests -v`: 14 tests covering file adapters and the local HTTP server.
- `node --test tests/test_core.mjs`: 5 tests covering frame/time conversion, prediction interval lookup, transition navigation, homography projection, physical distances, and timeline coordinates.
- `node --check inspector/static/app.js`: application module syntax.

The HTTP suite uses an ephemeral loopback port. The Python tests generate their own small metadata, tracking, homography, tagging, prediction, and byte-range fixtures. No competition assets are included.

## Browser verification

Tested in the Codex in-app browser, with the synthetic demo and a generated bundle loaded through **MatchDataset**, the same adapter used for the real match. The file-based fixture contains 1,800 frames, 22 tracks, homography, SportsCode tags, and two CSV predictions. A generated 72-second, 25-fps H.264 MP4 was used for video checks.

Verified:

- Initial render and pitch/tracking updates, with no browser console errors or warnings.
- Exact frame input, next/previous frame buttons, keyboard stepping, and playback.
- Frame 305 seeks the video to 12.204 seconds; stepping to frame 306 seeks to 12.244 seconds. These times lie within the corresponding 25-fps frames.
- Both browser-local file selection and server-streamed MP4 playback.
- At frame 260, ball status is missing and nearest-player evidence is unavailable; the two predictions remain independently displayed.
- Prediction transition navigation reaches frame 440, where the generated labels are `D` and the active tag is a throw-in.
- Tag filtering, next-tag navigation, slot labels, and the video overlay toggle.
- A URL containing `?frame=850` loads the streamed video at 34.004 seconds, with matching tracking, tags, and prediction intervals.
- Timeline zoom and pointer seeking. A drag within a 20-second window keeps its original coordinate window while dragging, then recenters when released.
- Gap navigation reaches the start of a missing-ball interval.
- Layout at a 390-pixel viewport, with document width equal to viewport width and no horizontal overflow. The temporary viewport override was reset after testing.

The screenshot in this directory shows **synthetic fixtures**, not the competition match. The generated video's moving square is a media-playback test signal; it is not ground truth for the synthetic ball track.

## Remaining verification

The licensed match bundle was unavailable. Actual-video alignment, compatibility with the delivered XML/TXT/CSV files, and startup/performance on the full 199,319-frame bundle are not claimed as verified. The implementation follows the public challenge starter formats, validates frame/slot counts, and reports malformed inputs rather than applying guessed offsets.

The viewer does not evaluate possession accuracy or replace the official submission validator.


# Independent review verification — 25 October 2026

Five completed independent cycles and their findings, fixes, rechecks, and limitations are recorded in REVIEW_CYCLES.md.

Current automated checks: `python3 -m unittest discover -s tests -v` passes 20 tests; `node --test tests/test_*.mjs` passes 18 tests. The JS suite now includes an actual-application controller harness with deterministic DOM/media/fetch doubles. It covers media coverage and dimensions, paused seeks, pending play cancellation, startup order, next-tag navigation, failed-window recovery, bounded outstanding requests, and fragmented full-match timeline drawing.

Additional main-agent browser checks confirmed exact frame 306 at video time 12.244 s, frame 1000 preserved beyond a 5-second video with an explicit unavailable-video placeholder, disabled projection with a warning for a 960 × 540 video, transition frame 440, and missing ball at frame 850. Synthetic data only; no browser console errors were observed. Performance measurements in the review log are synthetic controller/adapter measurements, not a real-video playback benchmark.


The final audit additionally verified the prediction-only mode with all four [organiser-published baseline outputs](https://github.com/metrica-sports/more-than-a-hack-2027/tree/main/evaluation/results). These are real model outputs for the match, not tracking or ground truth. The browser view at frame 11185 showed raw D versus A in all three smoothed files, with tracking marked Not loaded, no tracking requests, and no console errors. `published-predictions.jpg` records this view; `review-desktop.jpg` records the synthetic frame-850 inspection.

A fresh responsive override was attempted but did not change the hidden QA tab's DOM viewport from 1280 pixels; it was reset. No fresh 390-pixel pass is claimed for this revision. The initial narrow-layout result above remains historical evidence. Actual licensed match positions, video alignment, and licensed-bundle startup are still unverified.


# Repository integration verification — 3 November 2026

After integration with the challenge repository, all 20 Python tests and 18 JavaScript tests passed, along with `node --check inspector/static/app.js` and `git diff --check`. A CLI smoke test confirmed that a clean checkout containing only data/README.md opens the synthetic demo without explicit --demo. The shipped baseline_raw.csv loaded successfully, and the inspector derived the first-half [11185, 90652) interval from games.py. The official games.py and evaluation/ code were not modified. These checks do not add licensed-video or fresh-mobile verification claims. The user guide is TOUCHLINE.md.
