# FlickGPT technical document, More than a Hack 2027 Phase 1

This document describes the code that produced `FlickGPT.csv`. Every label in the file comes from that code. No person labelled any frame of the provided match, and no AI assistant produced or decided a label. Labels in the published 5-minute window shaped our first decoder on 21 October. "What the provided match informed" lists that and every other use of the match we know of. The section "Technical document detail" in [REPORT.md](experiments/hillclimb-2026-10-24/REPORT.md) keeps the earlier, longer text of every passage this document shortens.

## Terms

- **Labels.** H is Barcelona (home), A is Athletic (away), D is dead ball and X is abstain. Graded frames are the two halves the organisers score, where X takes the previous label.
- **spellF1** ranks submissions. A possession is a maximal run of H or of A. Predicted possessions are matched one to one with true ones by time overlap, with F1 averaged over overlap thresholds 0.3 to 0.7. **macroF1**, the per-frame F1 averaged over H, A and D, breaks ties.
- **baseline_smooth50** is the organisers' 50-frame majority-vote baseline. Our margins are spellF1 above it.
- **PFF** is the PFF FC World Cup 2022 tracking and event data. We split its 64 games into 32 selection games (PFF-A) and 32 held-out games (PFF-B).
- **m0 and m2** are two label conventions. m0 keeps per-frame labels, and m2 merges spells under 2 s into their neighbours. The provided match's convention is unknown to us.
- **Tactical ATD** is Metrica's automatic tracking from the tactical camera. **Smart Tagging** is Metrica's automatic event tags for the match. FAQ.md says Metrica generates them without manual review, and RULES.md lists them among the provided automatic inputs.
- **Token.** On a frame where the tracking shows the ball, the team of the nearest tracked player.
- **Synthetic worlds** are labelled Metrica and IDSSE games with the ball hidden. Renewal worlds draw gap lengths from the provided match's ball-missing runs. Transplant worlds lay the match's own ball-missing mask over labelled Metrica, IDSSE and PFF games. A group is one source under one convention.
- **Selection rule.** A rule, written before results are read, that picks the winner. The incumbent is the current best file.
- **Replacement bar.** A stricter test for replacing tier0_v13, written after it was frozen. The challenger must lead by more than 0.008 on PFF-A, lose at most 0.003 on any renewal or transplant group, and keep both PFF-B lower bounds above zero after a Bonferroni correction for an assumed 35 reads. It is REPORT.md's rule v3 gate 1, not the StatsBomb rule v3.

## Submitted file

| params file | sha256 of the CSV |
|---|---|
| `params/tier0_v20.json` | `2214a07626dda7c6ce5bca5356548df36b01f4aab534636be5031226bd685a6f` |

tier0_v20 is a hidden Markov decoder over the token, followed by rules for stoppages, short possessions, hand-over timing and tagged restarts. We chose it on 8 November as our best file, the only one that passes the replacement bar over tier0_v13. Three alternatives build with the same command and another params file.

- `params/tier0_v13.json` was our recommendation until then and is the fallback. Its CSV hashes to `8d980307e73c50e4a87ff3da4229aa9c73d11900f6fc00e4c670da1d53b77657`.
- `params/tier0_v22_pfffree.json` is the fallback if PFF's terms forbid weights fitted on its labels. Its CSV hashes to `fc1ac808756916ca446f247e2df10e2b764b0a18b53d28b20c5551d4f596236a`. On PFF-B it ties tier0_v13 (-0.0001 [-0.0031, +0.0030] under m0, +0.0009 [-0.0020, +0.0037] under m2). It was never compared with tier0_v20 directly.
- `params/tier0_v21.json` is a candidate outside our selection rule that also reads the broadcast tracking.

## Approach

### What we built

1. **Token.** Each seen-ball frame gets a token, with no distance threshold.
2. **Evidence.** A logistic model, the HMM's emission, gives the probability that the token's team really has the ball. Its weights are an intercept of 1.8596, -1.3627 on ln(1 + ball-to-nearest-player distance in m) and 1.0769 on ln(1 + team margin in m, capped at 30). The team margin is the gap between the two teams' nearest players. We fitted the weights on 1,869,449 live PFF-A frames with the ball seen. A missing ball gives flat evidence.
3. **Chain.** A four-state hidden Markov chain (H, A, dead after H, dead after A) runs forward-backward on 5-frame blocks. The emission likelihoods are first raised to the power 0.1, the temper, so one frame counts for little. The dead states remember the last team. The decoder picks the block labels that maximise the summed log posterior, minus 1 nat per change of team. A short run of the other team adds two changes, so it survives only when its summed log-odds exceed 2.
4. **Rules.** Run-level rules then decide dead ball, flip some short possessions, delay hand-overs and add stoppages at tagged restarts.

### Why this design

- **The ball is often missing.** It is missing on 41% of graded frames here. On other games, true team calls gain about three times as much as true dead-ball calls. Published touch detectors (Vidal-Codina et al. 2022; Link and Hoernig 2017) need a tracked ball, so we kept a chain that bridges gaps.
- **Posterior marginals, not Viterbi.** On a weak-evidence proxy, Viterbi called 93% of frames dead against 22% in the truth.
- **Run-level decisions.** Every frame-level team cue we tried lowered spellF1.
- **A learned model did not ship.** Fitted without PFF, it beat every rule file by at least +0.19 on synthetic worlds but lost to a PFF-free refit of tier0_v13 on real PFF-A gaps. The tactical ATD's ball statistics resemble PFF's, so it would likely lose here too.

### How constants were chosen

We chose constants by their scores on other games' labels. From tier0_v2 on, we wrote each selection rule before reading the results it judged. The exceptions are the original dead-ball rules, shaped on all 64 PFF games before the split, and the off-pitch threshold's PFF-B pass rule and the spell flip's tie order, both fixed after reading results. The push stage is also the best of 16 candidates on the same PFF-A games.

Synthetic worlds can only reject. A candidate falls if its margin drops more than 0.003 below the incumbent's on any group. We rank by the lower of the m0 and m2 margins on PFF-A, with a registered tie rule for gaps within 0.003. The winner must then beat the incumbent on PFF-B (90% paired per-game lower bound above zero) and stay above baseline_smooth50 on ten fresh synthetic seeds.

tier0_v20 took two steps from tier0_v13 under this rule. tier0_v19 added two touch features to the spell flip and lowered its cut to 0.75. On PFF-B it gained +0.0059 [+0.0033, +0.0085] (m0) and +0.0072 [+0.0043, +0.0100] (m2). tier0_v20 then added a later end to each dead run and the tag stoppage, registered as one test. Over tier0_v19 on PFF-B it gained +0.0034 [+0.0014, +0.0054] and +0.0027 [+0.0007, +0.0047]. At selection on PFF-A its m2 gain (+0.0029) sat inside the 0.003 tie band. Most of it is the end cut's, which alone had missed the selection bar and was never read on PFF-B. The replacement bar's PFF-B gains over tier0_v13, +0.0093 and +0.0099, are the sums of these two steps on the same games, so the bar adds no new evidence.

On PFF-B, tier0_v20's margin is +0.168 [+0.159, +0.177] under m0 and +0.207 [+0.197, +0.217] under m2 (90% per-game t intervals). PFF-B is not fully clean. Early probes pooled all 64 games, a chain grid scored it, and we reused it at least eighteen times without correction. Every lower bound is optimistic.

### What the provided match informed

No label of the match trained a model. These reads of it shaped our work.

- **Public window, 21 October.** Window spellF1 across tempers set the temper grid {0.02, 0.05, 0.1, 0.2}, and window counts partly argued the flat dead prior. We consulted the window for the mean possession length, the alive share and the choice of marginal decoding. We kept tier0_v0 over tier0_v1 partly on window spellF1 (0.412 against 0.310). tier0_v20 still carries the temper of 0.1 and the flat dead prior. Since 24 September EVALUATION.md had said never to choose between versions on the window. On 22 and 23 October RULES.md added that it is not a tuning set. Each params file records this under `provenance.public_window`.
- **Public window, from 24 October.** We read it five times, on frozen files only. The first read showed tier0_v7 predicting 25 possessions against 17, which may have steered later steps such as the switch penalty. tier0_v20 scored macroF1 0.662 and spellF1 0.441 there.
- **Dead-run length.** Ball-missing runs in the organisers' `baseline_raw.csv` suggested 101 and 126 frames as candidates for the shortest stoppage. PFF-A picked 126.
- **Synthetic gaps.** Renewal worlds use the match's ball-missing run lengths, its missing rate (0.411) and its dead-to-live missing ratio around Smart Tagging restarts (2.6). Transplant worlds use the match's ball mask whole. No rule or constant in any offered file is indexed by a frame of it.
- **Other match-wide reads.** The match's short-run statistics stopped tier0_v11's spell flip and passed tier0_v19's. Its track deficit and kick sharpness built harder dev worlds. We compared its input distributions with every training source and logged our output counts on it at every freeze.
- **Per-event checks.** Label-free probes read individual Smart Tagging restarts and matched broadcast frames to tactical ones. None set a numeric constant in an offered file. They did lead the test behind tier0_v20 to prefer, by registered order, the throw-in and goal-kick arm over one adding corners and free kicks. One probe's gap profile around corners shaped test worlds for a dropped rule.
- **Smart Tagging tags.** The submitted file reads the match's throw-in and goal-kick tags. They are automatic, so they are not human-produced data under RULES.md section 2. We adopted them on 27 October.
- **Pseudo-tags.** To test the tag stoppage on other games, we kept their set-piece events as pseudo-tags at per-kind rates set by the match's tag counts (throw-ins 0.65, goal kicks 0.67). Each starts 101 to 178 frames before its restart, the interquartile range of 23 kick onsets on the match that no code here reproduces. Committed code (`experiments/hillclimb-2026-10-24/tag_lead.py`) re-derives 108 to 264 frames, and Limitations gives the re-scored results. These statistics set no decoder constant, but they sit close to the rule against constants tied to specific frames.

The organisers have not ruled on match-wide statistics of automatic inputs or outputs. On 24 October we decided to allow designs shaped by them.

## Assets

### Used by the submitted file

- **Tactical ATD** (`_atd.xml` and `_atd.txt`), for the token, ball distance, team margin, off-pitch ball, ball speed, median player speed, push and touches.
- **Smart Tagging** (the XML), for its throw-in and goal-kick tags only.
- **Kickoff rows**, the organisers' documented kickoffs, hard-coded in `possession/challenge.py` (`KICKOFF_ROW`). With the graded-half bounds and frame count in `games.py`, they are the only frame-indexed values the code reads.

### Read only by an alternative

- **Broadcast ATD and homography** (tier0_v21). A tactical row with a missing ball takes the broadcast ball when both cameras show the same players. Each build maps frames by matching players.

### Tried and dropped

The submitted file reads no video, homography or broadcast tracking. REPORT.md ("What did not work") lists every dropped cue, such as ball speed in the emission, a free-kick stoppage and snapping hand-overs to the receiver's first touch.

## Training data

Every labelled dataset below is about other games, labelled by its provider, not us. Who made the labels is undocumented, and we assume analysts tagged events.

| dataset | source and licence | labels and who made them | amount | role |
|---|---|---|---|---|
| Metrica sample games | Metrica Sports public sample data | Metrica's event data, turned into per-frame H/A/D by our own rule in code | 3 games | veto worlds; part of the chain's original tuning; the emission fit and, on renewal worlds, the spell-flip fit of tier0_v22_pfffree |
| IDSSE (DFL) | Bassek et al. 2025, CC BY 4.0 | the DFL feed's BallStatus and BallPossession; whether a human corrected them is undocumented | 7 matches | veto worlds; the emission fit and, on renewal worlds, the spell-flip fit of tier0_v22_pfffree |
| PFF FC World Cup 2022 | PFF; no licence file, specifications marked proprietary, treated as all rights reserved | per-frame owner derived from PFF's game events by kloppy's reading | 64 games, 32 PFF-A and 32 PFF-B | ranking and confirmation; emission weights fitted on 1,869,449 PFF-A frames; spell-flip weights fitted on PFF-A labels |
| StatsBomb World Cup 2022 events | StatsBomb Public Data User Agreement | StatsBomb's possession team on the same PFF games | the same 64 games | a second convention in rule v3 and v4 rankings and confirmations, which shaped only tier0_v8, a file we do not submit; also scored in analyses published in REPORT.md (experiments 38, 39, 41 and 42) |
| SkillCorner Open Data | SkillCorner, MIT | SkillCorner's algorithmic possession group | 20 A-League 2024/25 matches | bench source only, outside every selection rule |

The pseudo-tags come from the set-piece events of the Metrica, IDSSE and PFF games. Their rate and lead, and the renewal worlds' gap statistics, are match-wide statistics of the provided match's automatic inputs. Transplant worlds use its ball-missing mask whole. None of these is a label.

**Credits.** Bassek, M., Rein, R., Weber, H. and Memmert, D. (2025). An integrated dataset of spatiotemporal and event data in elite soccer. *Scientific Data* 12, 195. doi:10.1038/s41597-025-04505-y. Tracking and phase data courtesy of SkillCorner (github.com/SkillCorner/opendata). Data source StatsBomb (github.com/hudl/open-data at `4b73468`). No file from these sources is in the repository. We have not settled whether a prize competition is commercial use under clause 1.2.2 of the StatsBomb agreement.

<img src="https://raw.githubusercontent.com/hudl/open-data/4b73468fc5b0f1950f9f66fada70ad3a4f9327cb/img/SB%20-%20Icon%20Lockup%20-%20Colour%20positive.png" alt="StatsBomb" width="240">

## Possession rules

The code applies these steps to each half in order (`possession/decoder.py`, `Decoder.decode` and `_rules`). Frames run at 25 per second.

1. **Before kickoff.** Every graded frame before the half's kickoff is dead. An abstention there would become a false possession.
2. **Chain.** The chain and its switch penalty give each 5-frame block H, A or dead.
3. **Dead ball.** These rules replace the chain's dead calls. A frame is a stoppage candidate in four cases.
   - The ball is unseen.
   - The ball is seen more than 0.5 m outside the pitch.
   - The ball moves under 1 m/s inside a run of at least 50 such frames.
   - The median player speed is under 0.5 m/s.

   A run of at least 126 candidate frames becomes dead, except its first 50 and last 30 frames, which keep their team. If the ball is seen more than 0.5 m outside the pitch on any frame from 25 before to 75 after the run's start, only 25 frames at the start keep their team. A run touching the half's first or last frame keeps none on that side. A stretch of team calls shorter than 150 frames between dead runs also becomes dead. Other frames keep the chain's team, and a frame the chain called dead takes the last team before it.
4. **Push flip.** A possession shorter than 250 frames, with no token on at least half its frames, goes to the other team when, averaged over the run, its players' median speed toward the goal they attack trails the other team's by 2 m/s or more.
5. **Spell flip.** A possession shorter than 250 frames, with a token on at least half its frames, goes to the other team when a logistic over 15 label-free run features, fitted on PFF-A labels, gives P(flip) of 0.75 or more. The features include length, token shares, ball speed, team margin, push, the chain's log-odds, the neighbouring runs and two touch features. A touch feature is the largest change in ball speed from 5 frames before to 5 after, at frames where the nearest player is within 1.5 m. touch_own uses frames where that player is on the run's team inside the run, and touch_other frames where it is on the other team within 25 frames of the run. Every run is scored on the labels left by the push flip, so one flip cannot change another's inputs.
6. **Hand-over lag.** Inside each run of team calls, every change of team moves 15 frames later. Changes into or out of dead ball stay put. On every labelled dataset, matched hand-overs came 10 to 22 frames early (median).
7. **Tag stoppage.** A Smart Tagging throw-in or goal kick starts a stoppage when under 20% of frames from 5 s before to 10 s after the tag are dead. The stoppage runs from the tag to the restart kick, the first frame 1 to 15 s after the tag where the seen ball passes 5 m/s within 1 s of being under 2 m/s. Without a kick the step adds nothing. Its window, share and speeds came from our exploring session's proposal (experiment 156) and were never tuned.

### Where the lines fall

- **Loose balls and challenges.** Far or contested balls give weak tokens, and a brief swap must exceed 2 nats, so a touch without control should rarely create a possession (inferred).
- **Restarts.** No rule names the restarting team. The dead state's memory and later tokens decide who restarts.
- **Abstention.** X appears only outside the graded halves.

## Limitations

### Where it fails

- **Short possessions.** An earlier file matched 2% of labelled PFF-A possessions under 2 s and 84% of those 20 s or longer. Short runs are called dead, given the wrong team or swallowed.
- **Stoppage edges.** On PFF-A under m0, true stoppage starts would gain 0.020 spellF1 and true ends 0.012. Most of that sits where our cues are silent.
- **Hand-over timing.** Moving every predicted boundary onto the nearest labelled one within 50 frames would gain 0.0283 spellF1 on PFF-A under m0. Ten label-free cues did not predict the offsets.
- **Label convention.** We do not know whether the ground truth credits brief touches (nearer m0) or only controlled possessions (nearer m2).

### Weaknesses of the evidence

- **PFF is a different tracker.** Its ball is missing on 58% of frames against 41% here. Synthetic worlds are biased too, because renewal masks switch exactly at label boundaries.
- **tier0_v20's step over tier0_v19 is thin.** With the pseudo-tag lead that committed code re-derives (108 to 264 frames), it falls to +0.0018 [-0.0003, +0.0038] (m0) and +0.0013 [-0.0008, +0.0033] (m2) on PFF-B. Against tier0_v13 it still gains +0.0077 [+0.0043, +0.0110] and +0.0084 [+0.0046, +0.0122], down from +0.0093 and +0.0099, mostly from tier0_v19's step, which uses no tags. tier0_v20 is never below tier0_v19 in these runs, so we kept it.
- **The tag stoppage may add nothing here.** Its tests used pseudo-tags that are never false, and it breaks even when 22% (m0) or 15% (m2) of its acts are false. Its expected part on the match ranges from about zero to about +0.005 (inferred).
- **The touch flip may transfer badly.** On the match it takes 15.3% of candidate runs, against 9.2% on PFF-A.
- **PFF terms.** PFF's files carry no licence, and we have not read the terms we accepted. tier0_v20 ships emission and spell weights fitted on PFF-A, as tier0_v13 does, and records the PFF manifest's sha256 (`pff_manifest_sha256`). If that is not allowed, tier0_v22_pfffree replaces it. It keeps PFF-ranked constants, so it is PFF-informed though not PFF-fitted.

### What we would fix with more time

- Detect touches where the ball is tracked.
- Find an anchor for stoppage end edges.
- Test the learned model on SkillCorner's real tracker gaps.

## Disclosures

- **AI assistants.** Claude (Anthropic) helped write the code and ran the experiments under our selection rules. Other Claude sessions reviewed the decision log, explored the data and scanned other teams' repositories. Claude, a cloud-hosted model, read the match's automatic inputs as aggregates, per-event probe outputs and the ball mask. The organisers clarified on 21 October that a coding assistant may inspect the data but must not produce labels. OpenAI Codex worked on this repository in parallel. None of its models or files ship, and its two candidate models served only as comparators on other games. Neither assistant produced or decided a possession label for the match. Our only reads of the match's labels are the public-window uses in "What the provided match informed". Claude drafted this document. The pipeline calls no cloud model at runtime.
- **Other teams' work.** From 27 October no data or insight from other teams' repositories entered our search. Earlier scans gave a dead-ball rule and a ranking mode, both retired, and ten experiments that changed nothing. Several teams also used set-piece tags as dead-ball evidence, but our tag stoppage's constants came from our own exploring session. Two kept steps were first sighted there. Our PFF loader removes a double-frame pattern that our own count confirmed, and tier0_v20's spell weights and selection read that loader. tier0_v21 recomputes its broadcast offsets by our own player matching.

## References

- Vidal-Codina, F., Evans, N., El Fakir, B. and Billingham, J. (2022). Automatic event detection in football using tracking data. *Sports Engineering* 25, 18. arXiv:2202.00804.
- Link, D. and Hoernig, M. (2017). Individual ball possession in soccer. *PLOS ONE* 12(7), e0179953. doi:10.1371/journal.pone.0179953.

## Reproduction

The environment is Python 3.11 with the pinned versions in `requirements-submission.txt`. tier0_v20 and tier0_v22_pfffree read the tactical ATD and the Smart Tagging XML. tier0_v13 needs only the tactical ATD. tier0_v21 also needs the broadcast ATD and the homography.

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-submission.txt
source .venv/bin/activate
export MTAH_DATA_DIR=/path/to/data            # the folder that holds the Barcelona v Athletic data bundle
python -m possession make-submission --params params/tier0_v20.json --out FlickGPT.csv
python evaluation/validate_submission.py FlickGPT.csv
shasum -a 256 FlickGPT.csv                     # or sha256sum; compare with the hash in "Submitted file"
```

Run the commands from the repository root. The build uses no random numbers, sums in a fixed order and rounds before each decision. We checked byte-for-byte rebuilds of tier0_v13, tier0_v20 and tier0_v22_pfffree from a fresh clone on macOS and in `python:3.11.14-slim` Linux containers on arm64 and x86_64 (emulated), with only the pinned packages and no network for the build. All three hashes matched on all three platforms. REPORT.md ("Reproduce") gives the selection commands, and `.audit/hillclimb-2026-10-24.tsv` logs every decision.
