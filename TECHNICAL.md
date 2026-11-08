# <team_name> technical document, More than a Hack 2027 Phase 1

This document describes the code that produced `<team_name>.csv`. Every label in the file comes from that code. No person labelled any frame of the provided match, and no AI assistant produced or decided a label. On 21 October, labels in the published 5-minute window set constants of our first decoder and helped us choose between our first two. Since 24 October the window has only been scored on frozen files, never inside a selection rule, though one early read may have steered later steps such as the switch penalty. "What the provided match informed" lists every use of the match we know of.

## Terms

- **Labels.** H is Barcelona (home), A is Athletic (away), D is dead ball and X is abstain. Graded frames are the two halves the organisers score, where X takes the previous label.
- **spellF1** ranks submissions. A possession is a maximal run of H or of A. Predicted possessions are matched one to one with true ones by time overlap, with F1 averaged over overlap thresholds 0.3 to 0.7.
- **macroF1** is the per-frame F1 averaged over H, A and D. It breaks ties.
- **baseline_smooth50** is the organisers' 50-frame majority-vote baseline. Our margins are spellF1 above it.
- **PFF** is the PFF FC World Cup 2022 tracking and event data. We split its 64 games into 32 selection games (PFF-A) and 32 held-out games (PFF-B).
- **m0 and m2** are two label conventions. m0 keeps per-frame labels, and m2 merges spells under 2 s into their neighbours. The provided match's convention is unknown to us.
- **Tactical ATD** is Metrica's automatic tracking from the tactical camera. **Smart Tagging** is Metrica's automatic event tags for the match. FAQ.md says Metrica generates them without manual review, and RULES.md lists this tactical tagging among the provided automatic inputs.
- **Token.** On a frame where the tracking shows the ball, the team of the nearest tracked player.
- **Synthetic worlds** are labelled Metrica and IDSSE games with the ball hidden. Renewal worlds draw gap lengths from the provided match's ball-missing runs. Transplant worlds lay the match's own ball-missing mask over labelled Metrica, IDSSE and PFF games. A group is one source under one convention.
- **Selection rule.** A rule, written before results are read, that picks the winner. The incumbent is the current best file. Dev means other games' labelled data used for development.
- **Replacement bar.** A stricter test for replacing tier0_v13, written after it was frozen. The challenger must lead the incumbent's native PFF-A minimum by more than 0.008, lose at most 0.003 on any renewal or transplant group, and keep both PFF-B lower bounds above zero, Bonferroni-corrected for 35 reads, an assumed count that was never taken. It is REPORT.md's rule v3 gate 1, not the StatsBomb rule v3.

## Submitted file

| params file | sha256 of the CSV | what it is |
|---|---|---|
| `params/tier0_v20.json` | `2214a07626dda7c6ce5bca5356548df36b01f4aab534636be5031226bd685a6f` | Hidden Markov decoder over the team of the player nearest the ball, then rules for stoppages, a flip for short possessions, a 15-frame delay on each direct hand-over between the teams, and a stoppage from a tagged throw-in or goal kick to the restart kick when the rules left the tag's surroundings mostly live |

We chose it on 8 November as our best file, the only one that passes the replacement bar over tier0_v13. Three alternatives build with the same command and another params file. `params/tier0_v13.json` was our recommendation until then and is the fallback. Its CSV hashes to `8d980307e73c50e4a87ff3da4229aa9c73d11900f6fc00e4c670da1d53b77657`. `params/tier0_v22_pfffree.json` is the fallback if PFF's terms forbid weights fitted on its labels. Its CSV hashes to `fc1ac808756916ca446f247e2df10e2b764b0a18b53d28b20c5551d4f596236a`. On the 32 held-out PFF games it ties tier0_v13 in spellF1 (-0.0001 [-0.0031, +0.0030] under m0, +0.0009 [-0.0020, +0.0037] under m2). It beats tier0_v20_pfffree (tier0_v20 with emission and spell weights refitted without PFF) by +0.0036 and +0.0045 but misses the replacement bar over it (+0.0043 against 0.008). It was never compared with tier0_v20 directly. `params/tier0_v21.json` is a further candidate outside our selection rule that also reads the broadcast tracking.

## Approach

### What we built

1. **Token.** Each seen-ball frame gets a token, with no distance threshold.
2. **Evidence.** A logistic model, the HMM's emission, gives the probability that the token's team really has the ball. Its weights are an intercept of 1.8596, -1.3627 on ln(1 + ball-to-nearest-player distance in m) and 1.0769 on ln(1 + team margin in m, capped at 30). The team margin is the gap between the two teams' nearest players. We fitted the weights on 1,869,449 live PFF-A frames with the ball seen. A missing ball gives flat evidence.
3. **Chain.** A four-state hidden Markov chain (H, A, dead after H, dead after A) runs forward-backward on 5-frame blocks. The emission likelihoods are first raised to the power 0.1, the temper, so one frame counts for little. The dead states remember the last team. The decoder picks the block labels that maximise the summed log posterior, minus 1 nat (natural-log unit) per change of team. A short run of the other team adds two changes, so it survives only when its summed log-odds exceed 2.
4. **Rules.** Run-level rules then decide dead ball, flip some short possessions, delay hand-overs and add stoppages at tagged restarts.

### Why this design

- **The ball is often missing.** On other games, swapping in true team calls gains about three times as much as true dead-ball calls. The ball is missing on 41% of graded frames here. Published touch detectors (Vidal-Codina et al. 2022; Link and Hoernig 2017) need a tracked ball, so we kept a chain that bridges gaps.
- **Posterior marginals, not Viterbi.** On a weak-evidence proxy, Viterbi called 93% of frames dead against 22% in the truth.
- **Run-level decisions.** Every frame-level team cue we tried lowered spellF1. Push, the median speed of a team's players toward the goal it attacks, helped only when judged once per mostly unseen possession.
- **A learned model did not ship.** Fitted without PFF, it beat every rule file by at least +0.19 on held-out Metrica and IDSSE synthetic worlds. On real PFF-A gaps it lost to a PFF-free refit of tier0_v13 (0.496 against 0.499 under m0, 0.517 against 0.546 under m2). The tactical ATD's seen-ball speed and touch acceleration resemble PFF's (Kolmogorov-Smirnov distance 0.05 and 0.09), so it would likely lose here.

### How constants were chosen

We chose constants by their scores on other games' labels. From tier0_v2 on, we wrote each selection rule before reading the results it judged, with three exceptions. We shaped the original dead-ball rules on all 64 PFF games before the split. We wrote the off-pitch threshold's PFF-B pass rule after reading that result. We fixed the spell flip's tie order (higher cut first, token-gated arm first) after reading its first results. The push stage is also the best of 16 candidates on the same PFF-A games.

Synthetic worlds can only reject. A candidate falls if its margin drops more than 0.003 below the incumbent's on any group. We rank by the lower of the m0 and m2 margins on PFF-A, with a registered tie rule for gaps within 0.003, usually to the incumbent or the smallest change. The winner must then beat the incumbent on PFF-B (90% paired per-game lower bound above zero) and stay above baseline_smooth50 on ten fresh synthetic seeds.

tier0_v20 took two steps from tier0_v13 under this rule. tier0_v19 added two touch features to the spell flip and lowered its cut to 0.75. It cleared selection by +0.0046 and gained +0.0059 [+0.0033, +0.0085] (m0) and +0.0072 [+0.0043, +0.0100] (m2) on PFF-B. tier0_v20 bundled two near-misses picked on PFF-A, a later end to each dead run and the tag stoppage, in one test registered before any run. It cleared selection by +0.0047, the m0 margin's gain. Under m2 its two parts sum to +0.0029 (experiment 162), inside the 0.003 tie band. On PFF-A most of the gain is the end cut's, which alone had missed the selection bar and was never read on PFF-B. Over tier0_v19 on PFF-B it gained +0.0034 [+0.0014, +0.0054] and +0.0027 [+0.0007, +0.0047], winning 20 and 21 of 32 games. It led in all 15 groups of the confirmation seeds, which earlier confirmations had read. Renewal masks favour a later dead-run end by construction, and the tag stoppage adds -0.0008 to +0.0007 there, so that lead is the end cut's.

The replacement bar re-aggregated those runs against tier0_v13 on 1 November, with thresholds set beforehand. Its PFF-B gains, +0.0093 under m0 and +0.0099 under m2 (Bonferroni lower bounds +0.0029 and +0.0026, 27 of 32 games won each), are the sums of the two steps above on the same games. Its native PFF-A leg (+0.0092) repeats the selection screens. So the bar adds no new evidence. Its gain was positive in all six transplant conventions. These figures score the tag stoppage on pseudo-tags that are never false. Under the match's ball mask on all 64 PFF games, the end cut alone adds +0.0006 [-0.0004, +0.0016] over tier0_v19 under m0 and the tag stoppage +0.0042 (experiment 182). If the match's tags are as imprecise as Limitations allows, tier0_v20's expected edge over tier0_v13 is about tier0_v19's (+0.0059 and +0.0072 on PFF-B). With every player PFF marks as estimated removed from PFF-A, every file stayed above baseline_smooth50 on all 32 games, and tier0_v20's gain over tier0_v13 grew to +0.0111 and +0.0112.

On PFF-B, tier0_v20's margin is +0.168 [+0.159, +0.177] under m0 and +0.207 [+0.197, +0.217] under m2 (90% per-game t intervals). It reads our fixed PFF loader. PFF's 29.97 fps tracking repeats each position for two frames, and our earlier nearest-frame resample made ball velocity jitter. tier0_v13's margin, +0.154 [+0.145, +0.163] and +0.192 [+0.182, +0.202], came from the earlier resample, so the two are not like for like. tier0_v22_pfffree's figures also use the fixed loader. PFF-B is not fully clean. A chain grid scored it, the probe behind the lag printed its rows, early probes pooled all 64 games, and we reused it at least eighteen times without correction. Every lower bound is optimistic.

### What the provided match informed

No label of the match trained a model. These reads of it shaped our work.

- **Public window, 21 October.** A smoke test scored spellF1 there across tempers and set the temper grid {0.02, 0.05, 0.1, 0.2}. Window counts partly argued the flat dead prior and bracketed an early generator. We also consulted the window, without setting values, for the mean possession length and alive share, both still in tier0_v20, and for choosing marginal decoding. We kept tier0_v0 over tier0_v1 partly on window spellF1 (0.412 against 0.310), though the only dev result favoured tier0_v1, and that decision dropped m0 from four dev sweeps. From tier0_v2 on, files went back to tier0_v1's chain values, so tier0_v0's token reliability (0.78) and restart prior (0.7), taken from window crosstabs, are not in tier0_v20. It still carries the temper of 0.1 from the window-set grid and the flat dead prior. EVALUATION.md had said since 24 September never to choose between versions on the window. On 22 and 23 October RULES.md added that it is not a tuning set. Each params file records this under `provenance.public_window`.
- **Public window, from 24 October.** We read it five times, on frozen files and never inside a selection rule. The first read showed tier0_v7 predicting 25 possessions against 17, a figure that may have steered later steps such as the switch penalty. After its freeze, tier0_v20 scored macroF1 0.662 and spellF1 0.441 there (22 possessions against 17).
- **Dead-run length.** Ball-missing run lengths in the organisers' `baseline_raw.csv`, built from the match's tracking, suggested the candidates 101 and 126 frames for the shortest stoppage. PFF-A picked 126.
- **Synthetic gaps.** Renewal worlds draw gap lengths from the match's ball-missing runs and target its missing rate (0.411). Their dead-to-live missing ratio (2.6, bracketed by 1 and 4) comes from the match's ball mask around Smart Tagging restarts. Transplant worlds served in measurements, in the replacement tests behind tier0_v20 and tier0_v22_pfffree, and as training rows for models that do not ship. The mask is an automatic input used whole. No rule or constant in any offered file is indexed by a frame of it, and it carries no label of the match.
- **Spell-flip refit.** tier0_v11's spell flip would have flipped 12.8% of the match's team runs, against 4% on PFF-A. Its registered transfer check then stopped it, because the median token share of the match's short runs (1.000) sat above PFF-A's 90th percentile (0.946). tier0_v12 refitted the flip on PFF-A labels without that feature. tier0_v19's touch-feature flip passed the same check (touch_own median 1.596, inside PFF-A's 0 to 2.641).
- **Other match-wide reads.** The match's per-team track deficit and kick sharpness built harder dev worlds, where re-selection kept tier0_v13's constants. We compared its input distributions with every training source, logged our output counts on it at every freeze, and found its tracking lacks PFF's double frames. Its ball-missing share after tagged restarts (61%) argued that synthetic worlds should only veto.
- **Per-event checks.** Label-free probes read individual Smart Tagging restarts, such as where the ball sat at each kick (experiments 106, 135, 143 to 147, 150, 155, 156 and 161), matched broadcast frames to tactical ones (166) and measured gaps against the broadcast camera (169 and 175). None set a numeric constant in an offered file. But the test behind tier0_v20 preferred by registered order the throw-in and goal-kick arm, the kinds where the tag stoppage acts on the match (experiments 156 and 157), over one adding corners and free kicks. One probe's gap profile around corners shaped test worlds for a dropped rule, and a fallback from the median tag lead was removed before tier0_v20.
- **Smart Tagging tags.** The submitted file reads the match's throw-in and goal-kick tags (Possession rules, step 7). They are automatic (see Terms), so they are not human-produced data under RULES.md section 2, and FAQ.md invites their use. We adopted them on 27 October.
- **Pseudo-tags.** To test the tag stoppage on other games, we kept their set-piece events as pseudo-tags at a per-kind rate set by the match's automatic tag counts (throw-ins 0.65, its 26 tags against a PFF median of 40 per game; goal kicks 0.67), with no reference to any label of the match. Each starts 101 to 178 frames before its restart, the interquartile range of 23 kick onsets on the match that our exploring session printed. No code in this repository reproduces that range, and we have not recorded how each onset was found. So on 8 November we re-derived it with committed code (`experiments/hillclimb-2026-10-24/tag_lead.py`). Measured from each throw-in or goal-kick tag to the kick that tier0_v20's own ball-speed detector finds, the interquartile range over 27 kicks is 108 to 264 frames. We then re-scored tier0_v20 with that lead (see Limitations). The pseudo-tags ranked, vetoed and confirmed tier0_v20, the submitted file, and tier0_v22_pfffree inherits them. They set no decoder constant but sit close to the rule against constants tied to specific frames.

The organisers have not ruled on match-wide statistics of automatic inputs or outputs. On 24 October we decided to allow designs shaped by them.

## Assets

### Used by the submitted file

- **Tactical ATD** (`_atd.xml` and `_atd.txt`), for the token, ball distance, team margin, off-pitch ball, ball speed, median player speed, push and touches.
- **Smart Tagging** (the XML), for its throw-in and goal-kick tags only, which start the tag stoppage.
- **Kickoff rows**, the organisers' documented kickoffs, hard-coded in `possession/challenge.py` (`KICKOFF_ROW`). Beside the graded-half bounds and frame count in the organisers' `games.py`, they are the only frame-indexed values the code reads. The code skips the kickoff helper in `games.py`, which is one frame off.

### Read only by an alternative

- **Broadcast ATD and homography** (tier0_v21). The homography maps broadcast pixels to pitch metres. A tactical row with a missing ball takes the broadcast ball when both cameras show the same players. Each build maps frames by matching players.

### Tried and dropped

REPORT.md ("What did not work") lists every dropped cue. Seven that tied, lost or failed confirmation follow.

- The tagged taker winning the first possession after a set piece.
- Live play during wide broadcast shots.
- Players closing on the ball.
- The ball's direction toward goal.
- Ball speed in the emission.
- A free-kick stoppage.
- Snapping hand-overs to the receiver's first touch.

The submitted file reads no video, homography or broadcast tracking. Smart Tagging's automatic tags are its only event input.

## Training data

Every labelled dataset below is about other games, labelled by its provider, not us. Who made the labels is undocumented, and we assume analysts tagged events.

| dataset | source and licence | labels and who made them | amount | role |
|---|---|---|---|---|
| Metrica sample games | Metrica Sports public sample data | Metrica's event data, turned into per-frame H/A/D by our own rule in code | 3 games | veto worlds; part of the chain's original tuning; the emission fit and, on renewal worlds, the spell-flip fit of tier0_v22_pfffree |
| IDSSE (DFL) | Bassek et al. 2025, CC BY 4.0 | the DFL feed's BallStatus and BallPossession; whether a human corrected them is undocumented | 7 matches | veto worlds; the emission fit and, on renewal worlds, the spell-flip fit of tier0_v22_pfffree |
| PFF FC World Cup 2022 | PFF; no licence file, specifications marked proprietary, treated as all rights reserved | per-frame owner derived from PFF's game events by kloppy's reading | 64 games, 32 PFF-A and 32 PFF-B | ranking and confirmation; emission weights fitted on 1,869,449 PFF-A frames; spell-flip weights fitted on PFF-A labels |
| StatsBomb World Cup 2022 events | StatsBomb Public Data User Agreement | StatsBomb's possession team on the same PFF games | the same 64 games | a second convention in rule v3 and v4 rankings and confirmations, which shaped only tier0_v8, a file we do not submit; also scored in analyses published in REPORT.md (experiments 38, 39, 41 and 42) |
| SkillCorner Open Data | SkillCorner, MIT | SkillCorner's algorithmic possession group | 20 A-League 2024/25 matches | bench source only; approved on 27 October and outside every selection rule, including those behind tier0_v19 and tier0_v20 |

The pseudo-tags that tested the tag stoppage come from the set-piece events of the Metrica, IDSSE and PFF games. Their rate per kind and their lead before the restart are match-wide statistics of the provided match's automatic tags and tracking (see "What the provided match informed"). Renewal and transplant worlds likewise carry the match's ball-missing statistics or mask, but no label of the match.

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
5. **Spell flip.** A possession shorter than 250 frames, with a token on at least half its frames, goes to the other team when a logistic over 15 label-free run features, fitted on PFF-A labels, gives P(flip) of 0.75 or more. The features include length, token shares, ball speed, team margin, push, the chain's log-odds, the neighbouring runs and two touch features. Each is the largest change in ball speed from 5 frames before to 5 after, at frames where the nearest player is within 1.5 m and belongs to the run's team inside the run (touch_own), or to the other team within 25 frames of it (touch_other). A possession whose own team shows no touch is more likely to flip. Every run is scored on the labels left by the push flip, so one flip cannot change another's inputs.
6. **Hand-over lag.** Inside each run of team calls, every change of team moves 15 frames later. Changes into or out of dead ball stay put. On every labelled dataset, matched hand-overs came 10 to 22 frames early (median), which we attribute to the token changing team mid-pass.
7. **Tag stoppage.** A Smart Tagging throw-in or goal kick starts a stoppage when under 20% of frames from 5 s before to 10 s after the tag are dead. The stoppage runs from the tag to the restart kick, the first frame 1 to 15 s after the tag where the seen ball passes 5 m/s within 1 s of being under 2 m/s. Without a kick the step adds nothing. Its window, share and speeds came from our exploring session's proposal (experiment 156) and were never tuned.

### Where the lines fall

- **Loose balls and challenges.** Far or contested balls give weak tokens, and a brief swap must exceed 2 nats, so a touch without control should rarely create a possession (inferred).
- **Restarts.** Tagged throw-ins and goal kicks can add a stoppage, but no rule names the restarting team. The dead state's memory and later tokens decide who restarts.
- **Abstention.** X appears only outside the graded halves.

## Limitations

### Where it fails

- **Short possessions.** An earlier file, before the push flip, switch penalty and spell flip, matched 2% of labelled PFF-A possessions under 2 s, 19% of those 2 to 5 s long and 84% of those 20 s or longer. Short runs are called dead, given the wrong team or swallowed.
- **Stoppage edges.** On PFF-A under m0, the true start of each stoppage tier0_v20 finds would gain 0.020 spellF1 and the true end 0.012. About three quarters of each gain sits where our cues are silent, starts with no ball seen going out and ends with no restart kick seen.
- **Hand-over timing.** On tier0_v20 under PFF-A m0, moving every predicted boundary onto the nearest labelled one within 50 frames would gain 0.0283 spellF1 (0.0203 from hand-overs between the teams), or 0.0130 within 25 frames. Ten label-free cues did not predict the offsets.
- **Label convention.** We do not know whether the ground truth credits brief touches (nearer m0) or only controlled possessions (nearer m2). Ranking on the worse of the two may suit neither.

### Weaknesses of the evidence

- **PFF is a different tracker.** Its ball is missing on 58% of frames against 41% here.
- **Synthetic worlds are biased.** Renewal masks switch exactly at label boundaries, and dev sources hold a lost ball in place.
- **tier0_v20's step over tier0_v19 is thin.** Widened for repeated reads of PFF-B, its lower bounds fall to about +0.0001 (m0) and -0.0006 (m2). That widening assumed about thirteen reads. PFF-B has had at least eighteen, so the true bounds are lower.
- **The pseudo-tag lead matters.** With the re-derived lead (108 to 264 frames), tier0_v20's step over tier0_v19 on PFF-B falls to +0.0018 [-0.0003, +0.0038] (m0, 19 of 32 games) and +0.0013 [-0.0008, +0.0033] (m2, 17 of 32), and no longer clears zero. A control run with the original lead reproduced the earlier figures exactly. Against tier0_v13, tier0_v20 still gains +0.0077 [+0.0043, +0.0110] (m0, 25 of 32) and +0.0084 [+0.0046, +0.0122] (m2, 24 of 32) under the re-derived lead. Most of that comes from tier0_v19's step, which uses no tags. tier0_v20 is never below tier0_v19 in these runs, so we kept it.
- **The tag stoppage may add nothing here.** Its tests used pseudo-tags that are never false. It breaks even when 22% (m0) or 15% (m2) of its acts are false. On the match at least 8 of its 10 acts are kicked from where the restart is taken, a weak test. Scaled from PFF-A per-act values, its expected part ranges from about zero (8 real acts) to about +0.005 (all 10 real) (inferred). That break-even may be pessimistic, because the false tags were drawn uniformly over open play.
- **The touch flip may transfer badly.** On the match, tier0_v19's flip, which tier0_v20 keeps unchanged, takes 15.3% of candidate runs, against 9.2% on PFF-A. We have no tier0_v20 figure. Its range check cannot catch a low touch_own, whose PFF-A 10th percentile is 0. tier0_v19 is at least the eighth spell-flip variant tried on these games.
- **PFF terms.** PFF's files carry no licence, its specifications call the data proprietary, and the terms we accepted are not on record. They may restrict machine-learning use, and we have not read them. tier0_v20's params file records the sha256 of the PFF file manifest we used (`pff_manifest_sha256`). tier0_v20 ships emission and spell weights fitted on PFF-A, as tier0_v13 does. If that is not allowed, tier0_v22_pfffree replaces it. A PFF-A screen picked its spell-flip recipe (the fourth tried) and it keeps PFF-ranked constants, so it is PFF-informed though not PFF-fitted.

### What we would fix with more time

- Detect touches where the ball is tracked.
- Find an anchor for stoppage end edges.
- Test the learned model on SkillCorner's real tracker gaps.

## Disclosures

- **AI assistants.** Claude (Anthropic) helped write the code and ran the experiments under our selection rules. Other Claude sessions reviewed the decision log, explored the data and scanned other teams' repositories. Claude, a cloud-hosted model, read the match's automatic inputs as aggregates, per-event probe outputs and the ball mask. The organisers clarified on 21 October that a coding assistant may inspect the data but must not produce labels. A second assistant, OpenAI Codex, worked on this repository in parallel. None of its models or files ship, and its two candidate models served only as comparators on other games. Neither assistant produced or decided a possession label for the match. Our only reads of the match's labels are the public-window uses above. Claude drafted this document. The pipeline calls no cloud model at runtime.
- **Other teams' work.** From 27 October no data or insight from other teams' repositories entered our search, and we know of no step in tier0_v13 or tier0_v20 derived from one, though tier0_v20 reads a loader fix first sighted there (below). Several teams also used set-piece tags as dead-ball evidence. Our tag stoppage's constants came from our own exploring session. Earlier scans gave a dead-ball rule and a ranking mode, both retired. Ten experiments came from leads there (REPORT.md's E41, E43, E47 to E50, E58, E59, P0 and E85) and changed nothing, though E58's blurred worlds re-checked tier0_v13. Two kept steps were first sighted there. Our PFF loader removes a double-frame pattern that our own count confirmed, and tier0_v20's spell weights and selection read that loader. tier0_v21 recomputes its broadcast offsets by our own player matching.

## References

- Vidal-Codina, F., Evans, N., El Fakir, B. and Billingham, J. (2022). Automatic event detection in football using tracking data. *Sports Engineering* 25, 18. arXiv:2202.00804.
- Link, D. and Hoernig, M. (2017). Individual ball possession in soccer. *PLOS ONE* 12(7), e0179953. doi:10.1371/journal.pone.0179953.

## Reproduction

The environment is Python 3.11 with the pinned versions in `requirements-submission.txt`. tier0_v20 reads the tactical ATD and the Smart Tagging XML, as does tier0_v22_pfffree. tier0_v13 needs only the tactical ATD. tier0_v21 needs the tactical ATD, the Smart Tagging XML, the broadcast ATD and the homography.

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-submission.txt
source .venv/bin/activate
export MTAH_DATA_DIR=/path/to/data            # the folder that holds the Barcelona v Athletic data bundle
python -m possession make-submission --params params/tier0_v20.json --out <team_name>.csv
python evaluation/validate_submission.py <team_name>.csv
shasum -a 256 <team_name>.csv                  # or sha256sum; compare with the hash in "Submitted file"
```

Run the commands from the repository root. The build uses no random numbers. Forward-backward sums in a fixed order, and the code rounds the posterior and the spell flip's features before each decision. Jittering every float decoder input by 1e-6 and 1e-4 relative changed no frame. We checked byte-for-byte rebuilds of tier0_v13, tier0_v20 and tier0_v22_pfffree from a fresh clone on a macOS laptop and in `python:3.11.14-slim` Linux containers on arm64 and x86_64 (emulated), each with only the pinned packages and, for the build, no network. All three hashes matched on all three platforms. REPORT.md ("Reproduce") gives the selection commands, and `.audit/hillclimb-2026-10-24.tsv` logs every decision.
