# Ball detector on the tactical video: feasibility, 2026-10-25

Can a local detector that never saw BAR-ATH labels find the ball on the tactical frames where the ATD
has none? This test used no labels. It compares the detector against the ATD ball where the ATD has one.

## Setup

- Detector: torchvision `fasterrcnn_resnet50_fpn_v2`, weights `FasterRCNN_ResNet50_FPN_V2_Weights.COCO_V1`
  from download.pytorch.org (COCO 2017, class 37 "sports ball"). There was no fine-tuning, and no BAR-ATH
  data entered the weights. The licence is BSD-3 (torchvision), so the AGPL question YOLO raises does not apply.
- Runtime: torch 2.14.1 and torchvision 0.29.1 in a throwaway environment, on Apple M3 Pro MPS. Frames were
  decoded locally with ffmpeg and never left the machine. The repo and its `.venv` are unchanged.
- Sample: 300 graded frames with a valid homography, drawn with seed 0. 150 have an ATD ball and 150 do not.
- Each frame was run in two modes, the full 1920x1080 frame and six 640x640 tiles upscaled 2x. Detections were
  mapped to pitch metres through the inverse tactical homography (`starter/load_homography.py`).
- The penalty spots and the centre spot score as balls. One variant masks 1.5 m around them.
- Script: `scratchpad/balldet/probe_balldet.py` (throwaway, not committed). Per-frame detections stay in the
  scratchpad. Only the aggregates below are recorded here.

## Results

Each line below uses the top on-pitch detection, any mode, spots masked, score at least 0.5.

| frames | measure | value |
|---|---|---|
| ATD ball present (150) | some detection | 93% |
| | top detection within 2 m of the ATD ball | 57% |
| | top detection within 5 m | 71% |
| | precision proxy (within 2 m / detected) | 0.61 |
| | median error when detected | 1.0 m |
| ATD ball missing (150) | one confident on-pitch detection | 71% |
| | of those, within 3 m of a touchline or goal line | 46 of 107 at score 0.5 (no mask) |

- Tiles beat full frames on recall: 57% against 47% within 2 m. Full frames at score 0.7 are a little more
  precise (0.71 against 0.64).
- On ATD-ball frames the wrong top detections (5 m or more off) are spread across the pitch: 33 of 150, and 9
  of those near a line. They are not one static object, so masking spots alone cannot fix them.
- On ATD-missing frames, nothing can check a detection. Since a top detection is right only about 60% of the
  time where it can be checked, roughly 40% of these are likely false. Many sit near the lines, where spare
  balls and balls out of play are.
- Runtime: 2.3 s per frame with tiles on MPS, plus 0.15 s to decode. All 199,319 frames would take about
  127 h. The 64,700 graded frames with no ATD ball would take about 42 h. A full-frame-only pass should be
  roughly 7 times faster (an estimate, not timed).

## Verdict: no-go for using detections directly, go for one more test

At about 60% per-frame precision, detections would feed wrong teams into the token on about 4 frames in 10.
That is worse than the decoder's current handling of gaps. Recall is high, though: when the ball is visible
the detector finds it 93% of the time, within about 1 m. So the problem is false positives, not blindness.

The next test, before any decoder change:

1. Run the detector on 10 to 20 contiguous gap stretches plus their edges, not scattered frames.
2. Link detections over time: constant velocity, anchored to the ATD ball at both gap edges, and drop
   objects that stay still for more than about 10 s (spots, spare balls).
3. Gate: on the ATD-ball frames at each gap's edges, the linked track must be within 2 m of the ATD ball
   at least 90% of the time. It must also cover at least 25% of gap frames. Below that, stop.
4. Only then feed the linked ball into `challenge.halves` as a second ball source, and run the label-free
   BAR-ATH transfer checks. PFF and IDSSE have no video, so they cannot score this.

Rules kept: no BAR-ATH labels, no hand-reviewed candidates, local model only, nothing derived from `data/`
committed.

## Outcome, 2026-10-26

The linked-track test ran on all 15 stretches and failed both legs. Within 2 m on edge frames: 895 of 1138
(0.786, gate 0.90). Gap frames filled: 775 of 5858 (0.132, gate 0.25). None of the 30 passes crossed a whole
gap. A candidate within 2 m of the true ball exists on only 0.656 of edge frames, so the detector's candidates
are the limit, not the linker. The detector does not enter `challenge.halves`. The full report is
`reports/ball-detector-linked-track.md` on branch `gis/balldet-linked-track` (commit c862dca).
