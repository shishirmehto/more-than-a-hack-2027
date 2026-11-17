# Five independent inspection and correction cycles

Objective: research and create the local inspection tool, then inspect and correct it through five cycles with independent judges.

Starting implementation: `2a1899d` (local possession inspection tool). The initial research is recorded in the workspace challenge notes and linked official format specifications in README.md. Initial creation and browser/unit-test evidence are recorded in docs/TESTING.md. This document records the subsequent independent reviews; an initial self-check is not counted as an independent cycle.

## Requirements used for the final audit

- Local, read-only inspection of tactical video, player/ball tracking, homography overlays, automatic tags, and multiple prediction timelines.
- Correct frame alignment, explicit missing/invalid data, and coherent seeking/playback across views.
- Useful keyboard, timeline, transition, and missing-ball navigation; usable narrow layout.
- Input validation, bounded data loading, and local-only handling of the licensed assets.
- Tests and browser evidence appropriate to each correction, with real-match limitations stated honestly.
- Five sequential cycles, each judged by a fresh independent reviewer, corrected as needed, and rechecked by that reviewer.
- Committed source, tests, documentation, and the review evidence.

## Cycle register

| Cycle | Independent judge | Focus | Status |
|---|---|---|---|
| 1 | `cycle1_data_judge` | Data fidelity and file adapters | PASS after corrections |
| 2 | `cycle2_sync_judge` | Video and tracking synchronization | PASS after corrections |
| 3 | `cycle3_interaction_judge` | Interaction and inspection usability | PASS after corrections |
| 4 | `cycle4_performance_judge` | Performance and local data handling | PASS after corrections |
| 5 | `cycle5_release_judge` | Independent final release audit | PASS after extension corrections |

## Cycle 1 — data fidelity

Initial verdict: changes required. The independent reviewer reproduced four P2 issues: extra tracking fields and invalid speeds hidden by NaN coordinates; absent team identifiers inventing home membership; duplicate CSV headers/uneven rows silently changing calibration; and finite singular matrices treated as usable.

Corrections: validate all observation fields before missingness, reject infinities with frame/slot context, require explicit team associations, reject ambiguous homography tables, and use a relative determinant check independent of matrix scale. Projection also rejects singular matrices while preserving valid scalar multiples.

Central verification: 18 Python tests and 5 JavaScript tests passed. Reviewer independently reran all four reproductions, 14 adapter tests and 5 JS tests, and checked dependent rows, overflow, the published calibration example, and scales 1e-250, 1e250, and -19. Final reviewer verdict: **PASS for all four required corrections**. No licensed match assets were used.

Deferred to later cycles: video dimension handling and friendly malformed-XML errors.


## Cycle 2 — synchronization and media lifecycle

Initial verdict: changes required. The fresh reviewer independently reproduced misplaced projection on resized video (P1), short-video seeks overwriting later tracking selections (P2), and longer videos continuing after tracking ended (P2).

Corrections: original 1920 × 1080 dimensions are required for projection, with explicit warnings otherwise; the tracking selection owns paused seeks; tracking outside media coverage stays selectable and can play with the tracking clock; video callbacks cannot overwrite paused/pending seeks; playback pauses at the final tracking frame. Source changes and pending seeks clear projection, and asynchronous play completion cannot undo pause.

The reviewer found a pre-manifest redraw regression during recheck. Guards and deferred local-video metadata activation fixed it; early file selection now survives manifest arrival.

Verification: 11 JavaScript tests passed centrally and independently. Reviewer additionally tested 56 duration/frame combinations, stale play rejection after source replacement, and early seeking/seeked/error/metadata events. Main-agent browser checks verified frame 306 at 12.244 s, frame 1000 retained beyond a 5-second video, and the 960 × 540 overlay warning, without console errors. Final independent verdict: **PASS**, with no remaining required synchronization fixes. All media and observations were synthetic.


## Cycle 3 — interaction and inspection usability

The fresh reviewer reproduced two P2 defects: stale next-tag navigation after seeking between empty intervals, and failed tracking chunks reporting Loading indefinitely (including late errors overwriting a newer ready view).

Corrections: include the upcoming filtered tag in the detail cache identity; render Unavailable consistently for failed tracking windows; gate error UI to the active window; add Retry tracking.

All 14 JavaScript tests passed centrally and independently. The reviewer also checked focused frame drafts and normalization, safe pre-manifest controls, filtered tag navigation in both directions, fixed drag bounds, and successful retry recovery. Final independent verdict: **PASS**, with no remaining required interaction fixes. Screen-reader behavior and real-match inspection were not claimed as tested.


## Cycle 4 — performance and local data handling

The fresh reviewer reproduced three P2 defects: drawing every interval on every frame caused 917–936 ms full-match redraws; 160 rapid seeks created 160 outstanding tracking requests; malformed XML escaped as a traceback.

Corrections: pixel-bounded overview bins use indexed interval lookup and explicitly mark mixed states; exact frame labels remain in detail cards. Transition lookup is logarithmic. Obsolete tracking requests are aborted, retaining at most the current window and one playback prefetch; cancellation never becomes a data failure. XML parsing now reports filename and context through the CLI error handler.

Independent synthetic full-size adapter baseline: 199,319 frames, 46 slots, eight maximally fragmented predictions (1,594,552 runs). Indexing 6.451 s; serialized manifest 62.2 MiB; peak RSS 676.9 MiB; random 125-frame read 4.4 ms. This intentionally extreme prediction case still has a large startup manifest; it is documented, not a real-match measurement.

Recheck: all 17 JS and 19 Python tests passed independently and centrally. Reviewer's same redraw benchmark improved to 0.85–4.52 ms per selected frame. Additional checks covered old-request completion after returning to a window, cancellation during JSON loading, and 1,000 mixed-bin interval cases. Both malformed metadata and tag XML exit with code 2 and contextual errors without tracebacks. Final independent verdict: **PASS** with no required performance/local-data corrections remaining.


## Cycle 5 — independent release audit

The fresh reviewer initially returned PASS with no required corrections after independently inspecting adapters, server, controller, markup/styles, README, and evidence. All 19 Python and 17 JS tests passed, as did app syntax. The reviewer also loaded all four organiser-published full-match prediction CSVs through the adapter, confirming complete coverage [0, 199319): raw 2,451 runs; smooth25 993; smooth50 811; smooth125 516.

While this cycle was running, the user requested real data in the manual-review tool. The shared challenge Drive requires sign-in and no licensed tactical observations were found locally. A prediction-only mode was therefore added for the genuine published baseline outputs, with explicit Not loaded tracking states and no synthetic observations. The same final reviewer rechecked the extension and found video warning/placeholder text that incorrectly implied tracking remained available. Those messages now correctly describe prediction inspection. Projection and slot controls are disabled without their data.

Current browser evidence: `review-desktop.jpg` shows the synthetic fixture at frame 850. A fresh 390-pixel override was attempted using the documented browser capability, but the hidden QA tab remained at 1280 pixels according to the DOM; the override was reset. No new narrow-viewport claim is made. The initial 390-pixel verification remains recorded in TESTING.md. Real licensed video/tracking alignment remains unverified.


Final extension recheck: **PASS after corrections, no required changes remain**. The reviewer independently passed 20 Python and 18 JavaScript tests plus application syntax, CLI error cases, absent-observation semantics, published CSV coverage, and prediction navigation. At frame 11185, the published raw baseline predicts D while all three smoothed versions predict A; this is model disagreement, not possession ground truth. Main browser verification of this view is recorded in `published-predictions.jpg` with no console warnings/errors. The four copied CSVs remain in ignored `local/published-baselines/`; they are not committed as source or mixed with synthetic observations.

All five sequential independent review/correction cycles are complete. The release is verified against format specifications, synthetic stress/controller fixtures, and published prediction outputs. Licensed tracking/video and fresh mobile-browser verification remain explicit limitations.


## Repository integration — 3 November 2026

The reviewed standalone history (through b29032d) was integrated onto the existing challenge repository. The challenge README and ignore rules were retained; the tool guide is TOUCHLINE.md. The inspector now reads match constants, asset names, and graded half blocks from games.py, without changing the official scorer or games.py. Default startup recognizes the committed data/README.md as an empty data bundle and opens the synthetic demo when no tracking files are present. The reviewed source checkpoints above describe the original local history, preserved separately, rather than the destination repository ancestry.
