# Possession labeller: design

The design behind `possession/`, chosen in a three-way design bakeoff (opus, fable, sonnet sketches, blind cross-judged) and synthesized from the winning sketch plus grafts (see "Synthesis decision"). Numbers marked measured came from throwaway bakeoff experiments that are not in this repo; the ones that matter are re-pinned by `python -m possession selfcheck`.

Evidence labels used below. **Measured** means a number I produced here, either on the real committed files or on a synthetic proxy that is named as such. **Inferred** means reasoned from the grounding. **Guess** means neither.

## Problem

We must label every frame of the match H/A/D, per half, X only outside play, from per-frame observations. Today the only full-match observation is `evaluation/results/baseline_raw.csv`. In that file D means "ball not observed" (85,831 rows, equal to 199,319 minus 113,488 ball-present frames), not dead ball. **Measured**: 66% of public-window GT-D frames have a visible ball (of 1469 GT-D frames the baseline says H 790, A 185, D 494). So a decoder must treat a missing ball as "no evidence" and carry state through dropout blocks. Those blocks are long. **Measured** on the file: 40.7% of graded frames are missing in both halves, in 69 and 81 runs with median 289 and 245 frames.

The public window has 17 possessions, so it checks correctness and cannot rank decoders. Ranking has to come from a Metrica dev set of about 430k labelled frames. That set must not leak Metrica's native ball NaN, which is an out-of-play marker, so the observation has to be rebuilt to look like the challenge's, with block dropout on alive and dead frames, team-level evidence and no identity.

Constraints the design honours. `evaluation/` and `games.py` are frozen. Labels come from code only, nothing uses the private GT, no match data goes to a cloud API. Data is never committed. The repo must regenerate the submission byte for byte, which forces the submission path to read only committed inputs. Scorer contract: H=0, A=1, D=2, X=3, graded spans are GT non-X runs, an X inside play splits spells, halves need enough X between them, and `pm.evaluate` does no range check. Dev output must avoid the gitignored names `*_possession_gt.csv` and friends.

## Usage (caller's view)

Written first. The types in Shape are derived from these call sites.

Shell, from the repo root:

```bash
python -m possession fetch-metrica --write-manifest     # once; later runs verify sha256, ~183 MB into data/metrica_sample/
python -m possession measure                            # match-wide aggregates behind the generator's constants; writes nothing
python -m possession fit-dev --seed 0 --rule m0 m1 m2 --out params/tier0_v1.json   # generator worlds default to dropout.CALIBRATION's bracket (1, 4)
python -m possession score --params params/tier0_v1.json --dev --public     # table; writes data/derived/runs/
python -m possession make-submission --params params/tier0_v1.json --out evaluation/results/possession_v1.csv
python evaluation/run_evaluation.py --bootstrap 1000    # existing scorer, unchanged, scores the CSV on the public window
```

`make-submission` reads `evaluation/results/baseline_raw.csv` and the params JSON. It uses no RNG and no Metrica files, so it reproduces the CSV byte for byte on a clean checkout. A params file that turns on a geometry term (the emission's `margin_scale_m`, `outside_bonus` or `far_bonus`, or `dead_outside_m` with `dead_min_run`, see `Decoder.needs_geometry`) is the exception. `make-submission` then decodes `challenge.halves("atd")`, so building its CSV needs the gated ATD on disk (`MTAH_DATA_DIR`), and without it the build stops with the IOError from `games.require`. The tokens are the same either way (`selfcheck.atd_reproduces_baseline_raw`). `fit-dev` is the only command that needs Metrica, and its product is a small JSON of numbers.

Python, score a decoder on three dev games, the pooled dev set and the public window. Two calls:

```python
from possession import bench, decoder

cases = bench.dev_cases(bench.DevSpec()) + [bench.public_case()]   # dev_g1, dev_g2, dev_g3, dev_pooled, public
table = bench.run({"v1": decoder.Decoder.load("params/tier0_v1.json")}, cases)
print(table[["model", "case", "spell_f1", "macro_f1", "n_pred_spells", "n_gt_spells"]])
```

Python, ask "what does it cost a decoder if the ball drops more on dead frames?", as a number per decoder choice. `measure` reads the real ratio at about 2.6, and the surface brackets it:

```python
from possession import bench, decoder, dropout

base = decoder.Decoder.load("params/tier0_v1.json")
worlds = {rho: bench.dev_cases(bench.DevSpec(dropout=dropout.DropoutParams(dead_bias=rho)))
          for rho in dropout.CALIBRATION.surface}            # (1, 2.6, 4)
print(bench.surface(base, worlds, beliefs=dropout.CALIBRATION.surface))   # rows generator dead_bias, cols decoder belief, last row = min over worlds
```

Python, the ATD plug-in. Switching a caller to the ATD is this one line (adopting it in `make-submission` is the open decision in "Next implementation step"):

```python
from possession import challenge, decoder
model = decoder.Decoder.load("params/tier0_v1.json")
halves = challenge.halves("atd")                  # was challenge.halves("baseline_raw"); returns the same two Half objects
preds = [model.decode(h).codes for h in halves]   # unchanged
```

## Shape

### Module map, organised by the knowledge each module owns

| module | owns | public surface | hides |
|---|---|---|---|
| `half.py` | codes, `Geometry`, `Half`, `CleanHalf`, `Layout` | the types, `check_codes` | array freezing, origin arithmetic |
| `score.py` | the only import of `pm` | `evaluate`, `spell_f1`, `write_submission`, `read_codes`, `matched_flags`, pm's run helpers | import style, range guard, assembly, newline and rename discipline |
| `challenge.py` | BAR-ATH: blocks, kickoffs, the tier-0 token, baseline_raw, the ATD seam, Smart Tagging | `halves(source)`, `layout`, `observe`, `nearest_team`, `Tag`, `tags`, `tag_rows` | the "D means missing" translation, the ATD and SportsCode grammars, club names to sides, the tag time-base check |
| `metrica/` | the sample data | `fetch`, `load`, `RuleV2`, `native_ball_seen` | pinned URLs, sha256, two file formats, label rule v2, native-NaN fill |
| `idsse/` | the seven DFL matches and their feed labels | `load`, `parse_match`, `MATCHES`, `REVISION` | the positions XML, the centre-origin flip, the sha256 manifest, the parse cache; it borrows `metrica`'s `fill_ball`, `merge_short` and `copy_hashing` |
| `pff/` | the 64 PFF FC World Cup 2022 games, labels from their game events, and the tracker's own ball-visibility flag | `load` (streams one game at a time), `native_seen`, `parse_game`, `GAMES`, `MANIFEST_SHA256` | the bz2 JSONL, duplicate frames, kloppy's label rule, the roster join, the 29.97 fps to 25 Hz resample, the centre-origin flip, the sha256 manifest, the parse cache; it borrows `metrica`'s `fill_ball`, `merge_short` and `copy_hashing` |
| `dropout.py` | challenge-ification and the generator's measured constants | `challengeify`, `DropoutParams`, `CALIBRATION`, `missing_rates` | rate solving, renewal masks, RNG streams |
| `measure.py` | how constants are measured: the real ball mask against Smart Tagging, constants counted on Metrica labels | `timeline`, `estimate`, `estimates`, `calibrated`, `counted_constants`, `report` | zones, dead-ball proxy definitions, the calibration rule, run splitting, coverage, the skip policy |
| `decoder.py` | evidence to labels | `Decoder.decode/replace/fields/save/load`, `Tier0Emission`, `DecoderParams` | chain, forward-backward, blocks, kickoff, tie rounding, range checks |
| `bench.py` | scoring problems and the selection protocol | `dev_cases`, `public_case`, `run`, `surface`, `fit_dev`, `paired_delta`, `Smoother`, `SOURCES` | which cases exist, worlds, max-min, the published floor |
| `selfcheck.py` | the invariants as runnable checks | `run` | |

This deliberately departs from the grounding's stage-shaped map (`halves / features / decode / sources / devset / submit / score`). Load, featurise, decode and submit are execution order, not ownership, and each stage would repeat the half bundle's rules (per `model-the-domain`: "execution order is not ownership"). Here, one module owns each body of knowledge. The longest user-visible chain is `bench -> dropout -> challenge` (three files), and `bench -> metrica -> metrica.rule` for labels. "Where does the generator's 2.6 come from?" is `dropout.CALIBRATION` -> `measure.calibrated` and `measure.estimate` -> `challenge.tag_rows` and `dropout.missing_rates`. Nothing on the submission path imports `measure`, `dropout`, `bench` or a dev source (`metrica`, `idsse`, `pff`), and `selfcheck` enforces an allow-list on the modules a fresh `make_submission` run loads.

### Data structures first

- `Geometry` (Level A): `ball_xy float32 [n,2]` metres NaN-for-unobserved, `players_xy float32 [n,S,2]` NaN-for-empty-slot, `slot_team int8 [S]`, `pitch_m`. Slots are anonymous. S=46 for the challenge, 22 to 28 for Metrica, 22 to 32 for IDSSE, and 22 to 32 for PFF (one slot per roster player seen in the half).
- `Half` (Level B): `HalfId(match, half, kickoff)` and `nearest_team int8 [n]` in {-1,0,1}. This is the decoder's whole input. `-1` means no evidence. It is a mask, never a dead-ball marker, and the type has no label field for a dead ball to sneak into.
- `CleanHalf`: `Geometry` with a fully observed ball, plus `labels int8 [n]` in {0,1,2}, plus provenance. Native NaN are filled upstream, so a decoder sees only the missingness a world injects: a synthetic mask, or in PFF's native worlds the tracker's own VISIBLE flag (`pff.native_seen`).
- `Layout`/`Block`: the only owner of origins. X exists only outside blocks. Invariant: at least 500 X rows before, between and after blocks, so `pm.valid_runs` returns exactly one run per half. The challenge layout is built from `games.half_video_blocks`, the dev layout is `Layout.synthetic`.
- `Case`: layout, halves, a scorer-length `gt` assembled from labels (derived, never stored twice). Its realised dropout is derived from halves and `gt` when a table needs it (`dropout_stats`).
- `Decoder`: frozen `(Tier0Emission, DecoderParams)`, each range-checked at construction, serialisable to JSON.

Geometry is a separate type from `Half` on purpose. `Half` is what both the tier-0 file (no geometry, ever) and the ATD path (geometry) can supply. Putting geometry on `Half` as an optional field would be "sometimes geometric", which forces an `if` into the decoder (per `type-system-discipline`, no bags of optional fields). The ATD-era `Half` adds a feature field with the richer `Emission`, with the contract in "Where the ATD plugs in".

### The decoder

```
Half --Emission.loglik--> float [n,3] evidence per label --forward-backward on 4 states--> P(H,A,D | all evidence) --argmax--> codes
```

The seam is the evidence matrix. The chain knows nothing about balls or teams. An `Emission` knows nothing about durations or kickoffs. Tier-0 is one `Emission`. The ATD-era feature model is another, and nothing else moves (per `boundary-discipline`, general mechanism inside and source-specific policy at the edge).

Four states: H, A, D_after_H, D_after_A. Both D states emit label D. D remembers the last possessor so a stoppage can carry a flip prior. On the Metrica labels 231 of 315 interior D stretches change team under the raw rule, and 176 to 185 under the controlled rules (`python -m possession measure`). Durations are geometric with per-class means. Evidence is tempered by a scalar alpha. Frames [0, kickoff) are D by rule. A missing ball is flat evidence unless the explicit `dead_bias` belief is set. Decoding runs on blocks of 5 frames.

Interface depth: `Decoder.decode(half)` is the whole decoding API. It hides the chain, scaling, block aggregation, kickoff handling and tie rounding. The caller supplies a `Half` and receives codes plus, under the default marginal rule, a posterior.

**Why posterior marginals and not Viterbi** (the grounding's default). Measured on a synthetic proxy: spells with median 6 s and 25% dead, and the REAL baseline_raw missing masks, 6 seeds by 2 halves, scored with `pm.evaluate`. Experiments `experiments/e1c_alpha_sweep.py` and `e1e_correlated_noise.py`.

| case | temper alpha | Viterbi (edge) | Viterbi + centre switches in flat blocks | posterior marginals |
|---|---|---|---|---|
| iid token errors, 46-state min-duration chain | 0.1 | 0.143 | 0.144 | 0.534 |
| | 0.2 | 0.470 | 0.476 | 0.624 |
| | 0.4 | 0.620 | 0.629 | 0.674 |
| | 0.8 | 0.660 | 0.677 | 0.695 |
| bursty token errors (acc 0.776), 4-state chain | 0.05 | 0.017 | 0.017 | 0.345 |
| | 0.1 | 0.176 | 0.178 | 0.423 |
| | 0.2 | 0.399 | 0.406 | 0.441 |
| | 0.4 | 0.421 | 0.432 | 0.429 |

Two effects. With weak evidence the MAP path hands whole stretches to the flat-evidence D state (D share of frames 0.93 at alpha 0.05 against 0.22 in the truth). That is the D-collapse, and posterior marginals do not do it. Inside a dropout block the MAP path puts the switch at a block edge, while the marginal puts it at the median of its posterior. Centring Viterbi by post-processing recovers only +0.000 to +0.017, so I dropped it. A well tuned Viterbi catches up at high alpha (0.432 against 0.429) but the optimum alpha moves between datasets and the posterior decoder does not fall off a cliff when it does. On the real tokens and the public window the two are not separated. An untuned 50-state Viterbi (alpha 0.1, `e1_decoder_feasibility.py`) scored 0.452 and the 4-state posterior scored 0.30 to 0.47 across alpha 0.01 to 0.1, on 17 possessions with noise of about 0.04. So the choice rests on the proxy's robustness-to-a-mistuned-temper argument, not on a real-data gap.

**Why four states and no minimum-duration chain.** Measured on the same proxy with posterior decoding (`e1d_min_duration_value.py`). Hard minimum 1 s changed spellF1 by +0.006 to +0.008, 2 s by -0.03, 3 s by -0.07 (iid-noise proxy). K from 4 to 60 states was not worth it.

**Real-data smoke test** (`e3_tier0_end_to_end_smoke.py`, untuned guesses). The shape yields a valid 199,319-row array from `baseline_raw.csv` in 0.15 s for both halves, 40,462 X rows outside the blocks, 2,934 pre-kickoff D rows in half 2, `pm.validate_submission` returns None. On the public window, at a mean spell of 6 s, spellF1 is 0.41 to 0.47 for alpha 0.01 to 0.05 with 14 to 17 predicted spells (17 in GT). The published baselines on the same window score 0.326 (smooth50) and 0.424 (smooth125). The window cannot rank these (noise about 0.04). What it does show is that the useful alpha range on real tokens is 0.01 to 0.1, much lower than on iid synthetic tokens, so alpha must be tuned on geometry-derived dev tokens. D is predicted on only 0 to 7% of window frames against 19.6% in GT. Tier-0 cannot see dead ball, and that is the honest limit of this observation.

**The dead-run stage** (`DecoderParams.dead_min_run`, `dead_trim`, `dead_close`, `dead_outside_m`; off by default). Tier-0's chain sees dead ball only through the flat-evidence prior, so on dev worlds it finds D far worse than smooth50 (f1_d 0.24 against 0.52) while calling teams better. With `dead_min_run` set, D is exactly the ball-missing runs of at least that many frames, shrunk by `dead_trim` at each end, plus any stretch of team calls shorter than `dead_close` frames with dead runs on both sides. A ball seen more than `dead_outside_m` metres off the pitch counts as missing (this needs `Half.geometry`, so the ATD). Every other frame keeps the chain's team, with the chain's own D filled from the previous call. `params/tier0_v2.json` is v1's chain with 126/50/150, and `params/tier0_v3.json` adds `dead_outside_m` 0.5. The 2026-10-24 hillclimb chose them on native PFF gaps, with the synthetic worlds as a veto, because the renewal generator switches masks exactly at label boundaries and so favours trims of 0 (`experiments/hillclimb-2026-10-24/REPORT.md`).

### The Metrica dev set

`metrica.load(RuleV2(merge_s, hold_s, min_passes))` returns six `CleanHalf`. `dropout.challengeify(clean, DropoutParams, seed)` returns six `Half`. Everything shaping a world is in `DevSpec`, namely the label rule, `dead_bias`, target rate, seed and fill rule.

- **Parse raw, no kloppy.** Two format parsers behind one `RawGame`. Coordinates to metres, no y flip. Periods split on the `Period` column. G3 slot team is asserted constant across substitution windows.
- **Labels from events only (rule v2).** Pure function `label_period(events, frame0, n, rule)`. Dead openers, restart closers, restart fallback, owner timeline, then either the controlled-possession filter or the merge (never both). Acceptance numbers are the explorers' (alive share 55.1/58.4/67.9%, raw spells 364/322/387).
- **Pre-kickoff is D, post-whistle is trimmed.** A half block starts at the period's first tracking frame and ends at the last event end plus one. Frames before kickoff are D. This mirrors the challenge's graded half 2 (2,934 D frames) and exercises the kickoff rule in dev. An X head would be back-filled by `pm.fill_abstentions` into a false spell, so D it is.
- **Native NaN fill.** Default `hold` (forward-fill, back-fill the head). It is a parameter, not an open question. The reason is that `linear` gives a dead ball a constant velocity that a ball-speed feature would read as live play, which is a different leak.
- **Dropout.** Alternating renewal process. Missing runs are resampled from baseline_raw's 146 real missing runs over each half's `[kickoff, n)`, present runs from its 145 present runs, scaled by the closed form `c = E[m](1-r)/(r E[p])` so the stationary rate is `r`. (Over whole blocks the counts are 150 and 149.) One mask for alive frames, one for dead frames, selected by label. `solve_rates(a, target, rho, cap)` solves both constraints given the half's alive share `a`. They are `a*p_alive + (1-a)*p_dead = target` and `p_dead = rho * p_alive`, with a cap and a loud failure if unreachable. The target is `dropout.CALIBRATION.window_rate`, 0.4110 (64,079 of 155,923 decode-window rows missing), the rate on the window the generator applies it to. Pre-kickoff is its own stratum at `CALIBRATION.prekickoff_rate`, 0.1922 (564 of 2,934 missing in the real half-2 stretch). It is inert for scoring, because the decoder reads `[kickoff, n)` only. A prototype of this generator (**measured**, `e2_dead_bias_surface.py`) realised an overall rate of 0.39 to 0.43 at target 0.407, and at rho 3 a P(missing | dead) of 0.83 and a P(missing | alive) of 0.27.
- **Identity.** Not simulated. `challenge.nearest_team` reduces over slots per frame, so identity-freedom is a tested property (`selfcheck.permutation_invariance`).
- **Seeds.** `SeedSequence([seed, game, half, stream])` per purpose (per `separate-before-serializing-shared-state`, no actor shares a generator, so adding a half or a stream reshuffles nothing).

### The harness and the selection protocol

Every scoring problem is a `Case`, so a decoder is scored by the same two calls on each Metrica game, on the pooled six halves, and on the public window. `score.py` is the only place that touches `pm`, asserts codes in 0..3 before every call, and assembles halves at their origins with X elsewhere.

`dead_bias` appears twice, on purpose. In `DropoutParams` it is the generator's world. In `Tier0Emission` it is the decoder's belief. `bench.surface` sweeps both and reports spellF1 per cell plus the minimum over worlds. **Measured** on the synthetic proxy, 4 seeds (`e2_dead_bias_surface.py`):

| generator dead_bias | belief 1 | belief 3 | belief 11 |
|---|---|---|---|
| 1 | 0.439 | 0.336 | 0.336 |
| 3 | 0.441 | 0.477 | 0.469 |
| 11 | 0.435 | 0.523 | 0.520 |
| min over worlds | 0.435 | 0.336 | 0.336 |

Wrongly believing missingness means dead costs 0.10, and wrongly ignoring it costs 0.09 in the dead-heavy world, so the surface is informative and asymmetric. The selection rule is therefore max-min over worlds, ties by mean. Worlds are the label rule (unknown for the real match) times `dead_bias` times the dropout seed (noise, see sweep 5). `measure` reads the real `dead_bias` at about 2.6 from Smart Tagging restarts, but its proxy has biases it cannot see, so `fit-dev` keeps the bracket (1, 4) from `dropout.CALIBRATION` (see "Measurements and constant provenance"). The `dead_bias` key is the requested ratio. Above roughly 8 the 0.98 per-state cap binds on high-alive halves and the effective ratio saturates (G3, alive share 0.68, at 11 gives about 7; the proxy's 78%-alive truth gave 4.2). 11 survives only as an explicit `--dead-bias 11` stress test. `bench.run` recomputes the realised rates from each case's tokens and prints them beside its scores, so a table never reports a ratio the data did not have. `dead_bias` is never fitted on the dev set, because fitting it there reads back the generator's own setting. Nothing else is fitted by counting either. `p_dead_after_poss` and `p_flip_after_dead` are grid axes like alpha, the two mean durations and the belief, because their counted values lost on the dev objective (see Dev sweeps). `q` is a grid axis too, but no recorded sweep varied it. Sweeps 1 and 2 counted it (`tier0_v1` has 0.7995), and sweeps 3 to 5 held it at v0's 0.78 (sweep 3's command is recorded only in its gitignored output), so no dev result isolates that value. Decode costs about 0.06 s per half at stride 5, so the 135-config by 3-world grid is a few minutes (**measured** decode time, grid size by arithmetic). `paired_delta` bootstraps the GT possessions two decoders share before anyone believes a gap under 0.04 (`score --paired`).

### Where invariants live

| invariant | mechanism, strongest available |
|---|---|
| X only outside play, halves split by `valid_runs` | `Layout` construction; `labels` typed 0..2 (no X inside a block), X added only by `assemble` |
| codes in 0..3 reach `pm` | `check_codes` at the single boundary (`assemble`, `evaluate`, `write_submission`) |
| missing ball is a mask, not D | `Half` has no label field; one translation function with a pinned self-check on the committed file |
| no native-NaN leak | `CleanHalf` postcondition (no NaN in ball), `dropout` is the sole source of NaN |
| identity-free evidence | `observe` reduces per frame; `permutation_invariance` check |
| deterministic submission | no RNG on the submission path; float64, no BLAS in the loop; posterior rounded to 9 digits before argmax; LF newlines, atomic write |
| repo hygiene | `write_submission` refuses `baseline_*` and `*_possession_gt*` names; dev output under `data/derived/runs/` |
| `pm` import style | one module, one line, and `assert (pm.H,...) == (H,...)` at import |

### Where the ATD plugs in and what it must produce

`challenge.load_geometry()` must return, per half, a `Geometry`: `ball_xy` and `players_xy` in metres (normalised times 105.3 and 68.0), NaN for `N` groups, S=46, `slot_team` from the XML `<Player teamId>` order with the first `<Team>` as home, rows equal to ATD `frame_id - 1` over `games.half_video_blocks`. `observe` turns it into a `Half`. The regression gate is that `observe` reproduces `baseline_raw.csv` on at least 99.99% of frames (exact equality is not promised, float32 can flip a near-tie). Measured on the real ATD (2026-10-22), it reproduces every token, 0 of 158,857 graded frames differ, so `selfcheck.atd_reproduces_baseline_raw` pins exact equality and skips when the data is absent. The parser reads the whole file with one `np.fromstring` (1.7 s), checks the line width and that frame ids run 1..199,319, and refuses metadata whose raw-line player order differs from the `<Player>` list. Its units guard is loose on purpose: the ball reaches a normalised y of 1.49. The XML `FieldSize` says 105 x 68, and the loader uses `games.py`'s 105.3 x 68.0 because the baseline does. Richer evidence is a feature field that `Half` gains with the richer `Emission`, computed in `observe`. The first one is `Half.geometry`, a `BallGeometry` of three float32 arrays from the same distances as the token: the team margin (nearest away minus nearest home distance, absolute), the nearest-player distance and the ball's distance outside the pitch. They are NaN exactly where the token is -1, and `selfcheck.permutation_invariance` pins them under slot permutation, padding and a team swap. Halves read from `baseline_raw.csv` have `geometry` None, and an emission that needs it raises there. `Tier0Emission`'s geometry terms read it: a per-frame q(margin) and D log-evidence for a ball off the pitch or far from every player, all off by default and left out of saved files when off. Their constants come from dev labels only (Metrica, IDSSE, PFF). Its columns are per frame, float32, slot-order invariant and team-paired (H then A, so a team swap equals a column-pair swap), NaN where the ball is unobserved, with ball-free columns that stay defined during dropout. Those ball-free columns are where the ATD era can beat tier-0, because a dropout block is 10 s of zero evidence today. Smart Tagging set-piece windows are a second source for the same feature contract.

### Principles that changed a decision

- `foundational-thinking`: the types came before the logic, and the Usage block was reconciled to them. It produced the `Half` / `Geometry` split.
- `exhaust-the-design-space` and `prove-it-works`: I ran competing decoders on the real masks and the real file before committing. It replaced the grounding's Viterbi default with posterior marginals and deleted the minimum-duration chain.
- `laziness-protocol`: it removed the switch-centring post-process, the npz cache, the HSMM duration tables, and a `features.py` that would hold one function.
- `model-the-domain` and `minimize-reader-load`: modules follow knowledge ownership, which keeps every user flow within three files.
- `type-system-discipline` and `encode-lessons-in-structure`: "missing is a mask" is a type fact, X-only-outside-blocks is a construction fact, and the rest are runtime checks at one boundary plus `selfcheck`.
- `boundary-discipline`: parsing, the range guard, URL pinning and file naming sit at the edges. The decoder and the dropout generator are pure functions.
- `separate-before-serializing-shared-state` and `make-operations-idempotent`: one RNG stream per half and purpose, and a `fetch` that converges after a crash.
- `build-the-lever`: `bench` and `selfcheck` are the reviewer's rerunnable artifacts.

## Synthesis decision

Base: this sketch (blind cross-judge total 29/30 against 27 and 22). It had the only reproduced evidence behind its decoder choices, the smallest decoder, an open `Emission` seam, and the cleanest split between the dropout generator's world and the decoder's belief, with a selection rule (max-min over worlds) that cannot read the generator back.

Grafted:

- From the opus sketch, the event rule as data: `metrica/rule.py` `Trigger`, `DEAD_TRIGGERS`, `NOT_RESTART`, `FALLBACK_RESTART`, `OWNER_KINDS`, `matches`. CHALLENGE-FAULT and the goal-kick fallback are now table rows, not comments.
- From the opus sketch, a second decode rule on the same 4-state chain: `DecoderParams.decode_rule = "map"` with `min_poss_frames` / `min_dead_frames` (shifted-geometric durations, exact prefix-sum MAP, `decoder._map`). The decoders disagreed and no design argument settles it, so it is a grid axis judged on the dev set. Default stays "marginal".
- From the opus sketch, the label-blind "transplant" dropout world (`DropoutParams.mode`), which copies a seeded window of the challenge's real mask and keeps its nonstationarity, and the `Case.__post_init__` guard (truth is X outside every block).
- From the fable sketch, fitting ignores truncated edge runs (`decoder.fit`). Removed with `decoder.fit` after sweep 3.

Rejected: boundary refinement (`_refine` / centring, measured at +0.000..0.017), posterior abstention and spell absorption (measured at noise or macroF1-only), the evidence-prior registries and binned naive-Bayes emission (speculative before any feature exists), the npz dev cache (invalidation surface), 46-slot tracklet simulation (needs the gated ATD to calibrate; tier-0 tokens cannot see it). Deferred: an explicit `ball_seen` mask on `Half` (needed once ball-only features exist), the turnover-biased dropout world.

## Tradeoffs accepted

- We accept that tier-0 barely predicts D (0 to 7% of window frames against 19.6% in GT, **measured** on untuned runs) in exchange for never teaching the decoder that a missing ball means dead ball. Dead-ball detection waits for features.
- We accept that posterior-argmax carries no duration guarantee in exchange for robustness to a mistuned temper and for centred switches. `bench.run` guards the predicted-to-GT spell ratio so flicker shows up immediately.
- We accept one scalar temper in place of a model of burst-correlated token errors (a clean/noisy regime in the emission) in exchange for a four-state chain. The dev tokens are geometry-derived and bursty, so tuning the scalar there is the cheap proxy.
- We accept geometric durations that are tuned, not fitted, in exchange for not baking Metrica's event convention (30% of raw spells under 2 s) into the challenge decoder.
- We accept H/A symmetry (no home advantage) in exchange for a decoder that cannot be fooled by a team-label swap and that three games cannot mis-estimate.
- We accept a stationary dropout generator that ignores play and camera in exchange for a bracketing sweep (`dead_bias` 1 to 4 around the measured 2.6) that does not pretend to know the real dependence exactly.
- We accept `hold` fill, which gives a dead ball a stationary position, in exchange for avoiding a constant-velocity dead ball. A ball-speed feature may still read "stationary" as a weak dead cue.
- We accept block decoding at stride 5 (switches quantised to 5 frames, tolerance in the scorer is 12) in exchange for a 5x faster grid. `stride=1` stays one parameter away.
- We accept committing selected numbers (`params/*.json`) derived from external public data in exchange for a submission path that never touches Metrica. Re-running the selection needs the fetch.
- We accept a documented kickoff constant (11185, 113742 from FAQ.md) rather than detecting kickoff. It is public, it is the rule the grader uses, and detection would add error on exactly the 2,934 frames the back-fill trap makes expensive.

## Alternatives considered

- **Stage-shaped modules** (grounding's map with `halves`, `features`, `decode`, `sources`, `devset`, `submit`). Lost on depth. `features.py` would hold one function today, the Level A/B bundle wants optional geometry on one type, and every stage repeats the half rules. The knowledge-owner map has fewer files a reader must open to answer "where does X come from".
- **Viterbi over a minimum-duration expanded chain** (the "safe pick"). Lost on the measured numbers above. It also puts every dropout-block switch at a block edge and collapses into D at low temper.
- **Explicit-duration HSMM with per-state duration tables.** Not measured, because the duration shape cannot be validated without the challenge's true durations and Metrica's are convention-biased. It costs a duration gather per step and an estimation step that would bake the convention in. Escape hatch if the dev set shows duration misfit. The `Emission` seam means swapping the chain touches only `decoder.py`.
- **One fat `Half` carrying geometry, features, labels and provenance.** Lost on type discipline. The tier-0 path can never fill geometry, and dev-only fields would be optional everywhere.
- **Per-frame independent or geometric-run dropout.** Lost on evidence. baseline_raw has 99.9% of missing frames in runs of at least 25 frames, so independent dropout would be trivially bridged and every decoder would look better than it is.
- **Caching challenge-ified Level A to disk.** Lost on cost and risk. Parsing all three games is about 5 s (inferred from the explorers' 1 s per game), dropout re-draws are cheap because the player array is shared, and a cache adds invalidation across `merge_s`, `ball_fill` and seed.
- **Fitting `dead_bias` on the dev set.** Lost because it reads back the generator. The surface replaces it.
- **Per-frame classifier plus HMM now** (hybrid). Deferred, not rejected. It is the ATD-era `Emission`. Tier-0 needs a table with two live numbers.

## Dev sweeps (2026-10-21)

`params/tier0_v0.json` is the reference decoder. The sweeps below ran on pooled dev with max-min selection. None of them replaced v0. They ran with the generator's old target 0.407, at commits up to `2f57fa0`, so reproducing their numbers needs that commit; later commits target 0.4110 and every dev score moves by draw noise.

| sweep | worlds | counts | winner | worst-world spellF1, winner / v0 |
|---|---|---|---|---|
| 1 | merge_s {0, 2} x dead_bias {1, 3} | fitted on m0 | `tier0_v1.json` | 0.313 / 0.294 |
| 2 | merge_s {2, 3, 5} x dead_bias {1, 3} | fitted on m3 | not kept | 0.327 / 0.335 |
| 3 | as sweep 2 | grid axes | v0 itself | 0.335 / 0.335 |
| 4 | controlled h{2, 3, 5}p3 x dead_bias {1, 3} | grid axes | v0 itself | 0.328 / 0.328 |
| 5 | as sweep 4 x seed {0, 1, 2} | grid axes | not kept | 0.325 / 0.315 |

- **The m0 world contradicts the challenge.** CHALLENGE.md says a touch, a deflection or a won duel without control does not change possession. Raw rule v2 has 33% of spells under 3 s, while m2 and m3 have 16% and 9%, and the public window has 18% (3 of 17). Sweep 1 was selected mostly on m0, so `tier0_v1.json` over-segments. It predicts 23 possessions on the public window against 17, and its spellF1 there is 0.310 against v0's 0.412. Use the controlled worlds below, or merge_s 2 or more.
- **Counted transition probabilities lose to hand-set ones.** The m3 counts give p_dead_after_poss 0.44 and p_flip_after_dead 0.56. Swapping them into v0 costs 0.025 and 0.006 spellF1 on the binding world, measured. The chain is misspecified (tempered, independent emissions), so the maximum-likelihood counts are not the spellF1 optimum. `fit-dev` no longer counts, and every chain field is a grid axis that defaults to v0.
- **Tier-0 has plateaued.** In sweep 3 the top 10 candidates lie within 0.004 of each other. v0 is interior on dead_mean_s, p_dead_after_poss and p_flip_after_dead, and on the lower edge of temper {0.05, 0.1} and poss_mean_s {6, 9, 13}. MAP lost to marginal in sweeps 1 and 2. Further gains need a richer emission from the ATD, not chain tuning.
- **Controlled possession is the faithful dev convention.** `RuleV2(hold_s, min_passes)` applies CHALLENGE.md's definition. The `RuleV2` docstring states the rule, and `selfcheck.controlled_rule_measurements` pins its spell counts. Measured on the three games, `hold_s` alone equals a left-to-right merge of short spells (0 of 426,640 frames differ at 1, 2, 3 and 5 s), the pass proxy changes labels only at 5 s (306 frames), and the set-piece clause changes none. "A few seconds" and "more than two consecutive passes" give the worlds h2p3, h3p3 and h5p3. Pooled spell lengths, measured (`python -m possession.metrica`):

  | rule | spells | mean s | median s | under 3 s |
  |---|---|---|---|---|
  | m0 (raw v2) | 1073 | 9.7 | 5.1 | 33.4% |
  | m2 | 825 | 12.6 | 8.2 | 16.4% |
  | m3 | 721 | 14.4 | 10.2 | 8.6% |
  | m5 | 595 | 17.5 | 12.6 | 9.2% |
  | h2p3 | 818 | 12.7 | 8.3 | 15.8% |
  | h3p3 | 709 | 14.7 | 10.3 | 8.5% |
  | h5p3 | 582 | 17.9 | 12.9 | 8.6% |
  | h5 (no pass proxy) | 578 | 18.0 | 13.1 | 8.7% |
  | p3 (no hold proxy) | 454 | 22.9 | 16.5 | 9.7% |
  | public window | 17 | 14.2 | 7.6 | 18% (3 of 17) |

  The public row is a correctness reference. Its 18% was also one of the figures cited when m0 was dropped (see "Measurements and constant provenance"). The pass proxy binds only from about 4 s: no rejected run shorter than 3 s holds two completed passes (h3p2 equals h3), so h2p3 and h3p3 equal h2 and h3. Passes alone reject every long run without a pass and are too coarse.
- **merge_s was a fair proxy.** At equal thresholds the controlled labels differ from the merged ones on 0.5% (2 s), 0.9% (3 s) and 2.2% (5 s) of live frames, and 97 to 98% of switches fall within 12 frames of each other. That difference is the scan order alone at 2 and 3 s, plus 306 frames from the pass proxy at 5 s, measured. Shortest first can hand a contested phase to the next team, while left to right keeps it with the last one. v0 scores within 0.002 of its merge-world scores at 2 and 3 s, and 0.007 to 0.010 lower at 5 s. v1 still loses. On the binding world h5p3_r1, v0 scores 0.3275 and v1 0.3017, a paired delta of -0.026 [-0.037, -0.014].
- **Sweep 4 keeps v0.** The grid is temper {0.05, 0.1}, poss_mean_s {6, 9, 13}, dead_mean_s {6, 10, 15}, p_dead_after_poss {0.15, 0.25, 0.4} and p_flip_after_dead {0.55, 0.7, 0.85}, with belief 1 and marginal decoding, 162 candidates. It ranks v0 first at seed 0, with the top 10 within 0.006. Promotion needed a max-min win over v0, a paired 90% CI excluding zero on the binding world, and a win again at seed 1. No candidate passed the first test, so `params/` is unchanged.
- **The dropout seed moves the ranking more than the paired CI shows, so sweep 5 makes it a world axis, and v0 stays.** The sweep 4 grid at seed 1 ranks v0 76th of 162, and the rank correlation of the per-candidate min between seeds 0 and 1 is 0.64. `paired_delta` resamples GT possessions within one dropout draw, so it misses the draw-to-draw spread, and v0's min alone moves 0.012 between the two seeds. Sweep 5 runs the same grid with `--seed 0 1 2`, one world per seed (`bench.worlds(seeds=...)`, keys like `h5p3_r1_s1`), so 18 worlds. Its winner is sweep 4's seed-0 runner-up (dead_mean_s 15, p_dead_after_poss 0.15, p_flip_after_dead 0.85), with min 0.3249 on h5p3_r1 against v0's 0.3153 on h5p3_r1_s1, and v0 ranks 30th with the top 10 within 0.0044. The two decoders bind on different worlds. On the winner's binding world it trails v0 by -0.0026 [-0.0069, 0.0017], and on v0's it leads by +0.0098 [+0.0052, +0.0145]. Held-out seeds 3 and 4 settle it. There the winner's min is 0.3158 against v0's 0.3187, and it leads on only 2 of the 12 worlds, so its edge was seed 1. `params/` is unchanged. Over seeds 0 to 4, v0's score on h5p3_r1 alone ranges from 0.315 to 0.347, about seven times the spread of the grid's top 10, so tier-0 chain tuning sits inside the draw noise. For a future promotion, held-out seeds replace "wins again at seed 1".
- **v0 against `tier0_v1` at the new calibration (2026-10-24): v0 on the controlled conventions, v1 on conventions that count touches.** `score --params params/tier0_v0.json params/tier0_v1.json --dev --rule h2p3 h3p3 h5p3 --dead-bias 1 2.6 4 --seed 0 1 ... 29` scores 270 worlds at target 0.4110, and the same command with `--rule m0 h1p3 m2` scores 270 more (commit 2f9efb5). Neither run scores the public window. The table gives v1 minus v0 spellF1. The "seeds" column averages the cells of each seed and puts a 90% t-interval over the 30 seeds. The "games" column puts one over the 3 games (t, 2 df).

  | rule | GT spells | over seeds | over games | worlds v1 wins |
  |---|---|---|---|---|
  | m0 | 1,073 | +0.0191 [+0.0178, +0.0205] | +0.0197 [-0.0003, +0.0397] | 90 of 90 |
  | h1p3 | 977 | +0.0164 [+0.0150, +0.0178] | +0.0169 [-0.0018, +0.0357] | 90 of 90 |
  | m2 | 825 | +0.0002 [-0.0010, +0.0014] | +0.0008 [-0.0239, +0.0255] | 46 of 90 |
  | h2p3 | 818 | -0.0011 [-0.0023, +0.0001] | -0.0005 [-0.0246, +0.0236] | 38 of 90 |
  | h3p3 | 709 | -0.0162 [-0.0175, -0.0148] | -0.0155 [-0.0389, +0.0080] | 1 of 90 |
  | h5p3 | 582 | -0.0332 [-0.0344, -0.0320] | -0.0331 [-0.0361, -0.0300] | 0 of 90 |

  The rule only relabels the GT. For a given dead_bias and seed, the ball mask and both decoders' predictions are the same under every rule. v0 predicts about 715 spells and v1 about 852, so the decoder whose count is nearer the GT's wins, and the crossover sits near 820 GT spells (m2 and h2p3). On the controlled set h2p3 to h5p3, v1 minus v0 is -0.0168 [-0.0180, -0.0157] over seeds and -0.0163 [-0.0325, -0.0002] over games, and seeds 0 to 14 and 15 to 29 agree. `bench.SELECTION` picks v0 there (min 0.3017 against 0.2782), still picks v0 with h1p3 added (by 0.0001), and picks v1 with m0 added (0.2782 against 0.2655). The seed interval covers dropout draws only. The game interval is the one that speaks to a new match, and it barely excludes zero. macroF1 favours v1 in every world (+0.0517), almost all of it from v1's f1_d (0.21 against 0.05). The seed-0 number in the verify-possession score recipe (+0.0038 at h3p3_r1) is the only one of 30 seeds in which v1 wins that cell. So the permitted evidence picks v0 under CHALLENGE.md's controlled-possession convention and v1 under conventions that count touches. It cannot say which one BAR-ATH's GT resembles, and the public window may not be used to find out.
- **v0 against the window-50 smoother (2026-10-24): v0 scores higher on dev worlds under every convention, and the game interval excludes zero only on h3p3, h5p3 and the controlled set.** `bench.Smoother` ports `starter/baseline.py`'s majority vote, and `score --baseline 25 50 125` scores it beside the params files. On BAR-ATH it equals the committed baseline files on every graded frame, and its public-window scores equal the README board (`selfcheck.smoother_matches_published_baselines`). `score --params params/tier0_v0.json --baseline 25 50 125 --dev --dead-bias 1 2.6 4 --seed 0 1 ... 29`, once with `--rule h2p3 h3p3 h5p3` and once with `--rule m0 h1p3 m2`, scores 540 worlds at the commit that adds `Smoother`. The table gives seed-mean pooled spellF1, then v0 minus smooth50 with a 90% t-interval over the 3 games.

  | rule | v0 | smooth25 | smooth50 | smooth125 | v0 minus smooth50, over games | worlds v0 beats smooth50 |
  |---|---|---|---|---|---|---|
  | m0 | 0.3127 | 0.2626 | 0.2972 | 0.2487 | +0.0141 [-0.0455, +0.0736] | 69 of 90 |
  | h1p3 | 0.3308 | 0.2637 | 0.3064 | 0.2625 | +0.0230 [-0.0393, +0.0852] | 87 of 90 |
  | m2 | 0.3591 | 0.2475 | 0.3075 | 0.2857 | +0.0501 [-0.0118, +0.1120] | 90 of 90 |
  | h2p3 | 0.3592 | 0.2450 | 0.3057 | 0.2868 | +0.0521 [-0.0091, +0.1133] | 90 of 90 |
  | h3p3 | 0.3708 | 0.2198 | 0.2890 | 0.3043 | +0.0802 [+0.0250, +0.1354] | 90 of 90 |
  | h5p3 | 0.3496 | 0.1770 | 0.2437 | 0.3024 | +0.1047 [+0.0605, +0.1489] | 90 of 90 |

  At the measured dead_bias 2.6, v0 minus smooth50 on the controlled set is +0.0739 [+0.0709, +0.0769] over seeds and +0.0725 [+0.0193, +0.1257] over games. Over all three dead_bias values it is +0.0804 [+0.0790, +0.0818] over seeds and +0.0790 [+0.0262, +0.1318] over games. Against the best of the three windows in each world, the controlled margin is +0.0552 [+0.0536, +0.0567] over seeds and +0.0522 [+0.0148, +0.0895] over games. Over all six rules v0 minus smooth50 is +0.0555, and the game interval [-0.0029, +0.1110] just includes zero. In the 540 pooled worlds v0 beats smooth25 and smooth125 every time and loses to smooth50 24 times (21 on m0, 3 on h1p3). Per game it also loses to smooth25 or smooth125 in 31 of 1,620 game worlds. `bench.SELECTION` ranks v0 first on both rule sets (controlled min 0.3017 against smooth125's 0.2285).

  The margin is mostly a spell-count effect. On average v0 predicts 715 spells, and smooth25, smooth50 and smooth125 predict 1,925, 1,503 and 1,019, against GT counts of 582 to 1,073. The smoothers split possessions and v0 merges them. The margin over smooth50 shrinks as dead_bias grows: +0.077, +0.049 and +0.040 at 1, 2.6 and 4 over all six rules, and +0.1024, +0.0739 and +0.0649 on the controlled set. The smoother turns long ball-missing runs into D, and those runs fall more in dead time as dead_bias grows. The same rule makes macroF1 favour every smoother (smooth50 0.577 against v0's 0.433): their f1_d runs from 0.32 to 0.53 against v0's 0.05. A long missing run is dead-ball evidence that v0 ignores at belief 1.

  Three limits apply. There are only three games, and game 3 gives the largest margin under every rule: on m0, v0 minus smooth50 is -0.0125, +0.0006 and +0.0542 on games 1, 2 and 3. The dev sweeps above retained v0 over its grid neighbours on these same games, so the margin is not an out-of-sample estimate for v0. And the README's full-match baseline scores derive from the private GT, so nothing here uses them to tune or to choose a convention.
- **IDSSE, the DFL feed's own labels (2026-10-24): v1 beats v0 on every merge rule up to 2 s, and on the feed's labels v0 falls below smooth50.** `idsse.load` reads seven German league matches (two Bundesliga, five 2. Bundesliga) of DFL tracking at 25 Hz (Bassek et al. 2025, CC BY 4.0) and labels each frame D where the ball frame's BallStatus is 0, else H or A from BallPossession. CHALLENGE.md says BAR-ATH's GT is derived the same way, mechanically from a tracking provider's dead flag and ownership flag, so these labels are the nearest permitted analogue we have. The provider differs (TRACAB for the DFL), and its ownership rule may split possessions more or less finely than BAR-ATH's. `score --params params/tier0_v0.json params/tier0_v1.json --baseline 25 50 125 --dev --source idsse --rule m0 m1 m2 m3 --dead-bias 1 2.6 4 --seed 0 1 ... 29` scores 360 worlds. The table gives seed-mean pooled spellF1 and the GT possession count. Intervals are 90% t-intervals over the 7 matches (6 df).

  | rule | GT possessions | v0 | v1 | smooth25 | smooth50 | smooth125 | v1 minus v0, over matches | v0 minus smooth50, over matches |
  |---|---|---|---|---|---|---|---|---|
  | m0 | 3,061 | 0.2281 | 0.2528 | 0.2479 | 0.2476 | 0.1847 | +0.0244 [+0.0202, +0.0287] | -0.0190 [-0.0293, -0.0086] |
  | m1 | 2,561 | 0.2562 | 0.2808 | 0.2569 | 0.2680 | 0.2069 | +0.0244 [+0.0185, +0.0303] | -0.0117 [-0.0226, -0.0008] |
  | m2 | 2,042 | 0.2938 | 0.3088 | 0.2474 | 0.2782 | 0.2383 | +0.0149 [+0.0098, +0.0199] | +0.0154 [+0.0049, +0.0259] |
  | m3 | 1,717 | 0.3138 | 0.3151 | 0.2240 | 0.2699 | 0.2584 | +0.0012 [-0.0066, +0.0090] | +0.0440 [+0.0299, +0.0580] |

  On the feed's labels (m0), v1 beats v0 in all 90 pooled worlds, and its seed-mean lead is positive on every one of the 7 matches (+0.018 to +0.034). v0 beats smooth50 in 6 of 90 pooled worlds and loses on 6 of the 7 matches. v1 minus smooth50 is +0.0055 [-0.0026, +0.0136], so v1 is level with the floor there, not clearly above it. `bench.SELECTION` picks v1 on m0 alone and on all four rules (min 0.2150, against v0's 0.2012 and smooth50's 0.2001). The mechanism is the same as on Metrica: on average v0 predicts 1,680 possessions, v1 1,938 and smooth50 3,417, against 3,061 on the feed's labels, so both decoders merge far more than the feed splits. v1's lead fades as the merge rule coarsens the GT towards the decoders' counts. macroF1 again favours every smoother (0.55 to 0.56 against v1's 0.44 and v0's 0.38), almost all of it from f1_d (v0 0.03).

  Taken with the Metrica table above, v1 wins on every convention that keeps touch-level hand-overs (Metrica m0 and h1p3, IDSSE m0 to m2), and v0 wins only on Metrica's controlled rules h2p3 to h5p3. The limits: seven matches from one league and one provider; synthetic dropout calibrated on BAR-ATH, not native gaps; and the source paper says only that BallPossession names "the player in control of the ball", with no published rule for duels, loose balls or hand correction. Nothing here reads the public window or the README's full-match scores.

## Measurements and constant provenance (2026-10-23)

Upstream f8f2629 (2026-10-23), not yet merged into this branch, excludes the public window as a source for any decoder or generator constant: upstream RULES.md section 2 calls the public minutes "not training data and not a tuning set". EVALUATION.md had already said, since 2026-09-24, to use the window to check correctness and "never to choose between two versions of it". Upstream RULES.md has no clause about match-wide statistics. Our reading, which the organisers have not confirmed, is that statistics of the automatic inputs computed by code and tied to no specific frame are allowed. Upstream rule 1 permits "inspecting the data to understand them, debug your pipeline and design features" and "pseudo-labels produced by an algorithm, provided no person decided any of them", and it bans "rules and constants tied to specific frames of the game". `python -m possession measure` re-derives the generator's constants from the tactical ATD ball mask and Smart Tagging (both automatic), and the decoder's countable constants from the Metrica labels (other games). It prints aggregates only and writes nothing. `selfcheck.measure_pins_calibration` and `controlled_rule_measurements` pin its counts, which an independent probe measured. Every number `measure` reports below is **measured**.

The ball mask by zone. The decode window is `[kickoff, n)` of each half.

| zone | frames | missing | rate | missing / present runs |
|---|---|---|---|---|
| window, half 1 | 79,467 | 32,304 | 0.4065 | 69 / 68 |
| window, half 2 | 76,456 | 31,775 | 0.4156 | 77 / 77 |
| window, both | 155,923 | 64,079 | 0.4110 | 146 / 145 |
| pre-kickoff, half 2 | 2,934 | 564 | 0.1922 | 4 / 5 |
| graded, both | 158,857 | 64,643 | 0.4069 | 150 / 149 |

The old target 0.407 was the graded row. The generator applies its target on the window, so `CALIBRATION.window_rate` is 0.4110. The ATD mask equals baseline_raw's on every frame, and the two run pools are identical.

The dead-ball proxy. Smart Tagging has 638 instances, 59 of them set pieces: 26 throw-ins (all team "N/A"), 12 corners, 10 goal kicks, 5 free kicks, 4 kick-offs after a goal and the 2 opening kick-offs. The tag time base agrees: the opening kick-off tags contain rows 11185 and 113742. The dead stretch precedes a restart's tag start. P(missing) by offset from the start of each of the 57 restarts:

| offset s | [-60, -55) | [-55, -50) | [-50, -45) | [-45, -40) | [-40, -35) | [-35, -30) | [-30, -25) | [-25, -20) |
|---|---|---|---|---|---|---|---|---|
| P(missing) | 0.386 | 0.302 | 0.361 | 0.328 | 0.338 | 0.378 | 0.421 | 0.480 |

| offset s | [-20, -15) | [-15, -10) | [-10, -5) | [-5, 0) | [0, 5) | [5, 10) | [10, 15) |
|---|---|---|---|---|---|---|---|
| P(missing) | 0.507 | 0.639 | 0.633 | 0.732 | 0.613 | 0.285 | 0.177 |

Every 5 s bin from -60 to -30 s runs 0.30 to 0.39, and every bin from -30 s to the tag start runs 0.42 or more, so the "phase" alive side keeps 30 s clear of every set piece (`measure.PHASE_GUARD_S`).

Each of the 4 goals tags runs on through the stoppage to the kick-off after the goal: it ends 1 s after that kick-off's tag starts and lasts 71 to 251 s. Their 16,503 window rows are missing 0.883 of the time. The length and the rate say those rows are mostly stoppage (inferred), so `Tag.phase` excludes goals tags and both alive sides drop their rows.

The headline proxy is the 5 s before each restart against the rest of the window outside goals tags: 5,214 of 7,125 against 45,069 of 133,098, a ratio of 2.161. There are 16 definitions: lead 3, 5, 10 or 15 s, tail 0 or 5 s, and an alive side that is either the rest of the window or only team phases outside every set piece and its 30 s lead. Across them the ratio runs from 1.999 to 3.445, median 2.579. The 8 "rest" definitions have median 2.121 and the 8 "phase" ones 3.048. The phase alive side is 11,113 missing of 50,813 (0.219). Per restart kind at lead 5 s, the ratio against the rest runs from 1.41 (goal kick) to 2.95 (corner, kick-off after goal), and against the phase side from 2.18 to 4.57. Untagged window rows are missing 0.555 of the time.

Two rules turn the 16 definitions into the generator's worlds (`measure.calibrated`). The point world is their median to one decimal, 2.6. The bracket runs from 1, where missingness says nothing, to the ceiling of the largest definition, 4. The per-kind ratios are reported, not bracketed: each rests on 4 to 26 restarts. A proxy whose lead rows are partly live play understates the true ratio. World 4 shows the median only if 52.6% of the proxy's rows are dead ball, and world 11 only if 15.8% are (`measure.implied_purity`).

Players stay tracked through dropout. On missing window frames the tracker holds 18.2 players on average in half 1 and 20.1 in half 2, against 21.4 and 21.5 on present frames. That is what ball-free features can use.

Decoder constants counted on the Metrica labels over each half's `[kickoff, n)`. q is counted on alive frames whose ball the source file observed.

| constant | v0 | m0 | h2p3 | h3p3 | h5p3 |
|---|---|---|---|---|---|
| q | 0.78 | 0.8029 | 0.7977 | 0.7927 | 0.7814 |
| alive_share | 0.6 | 0.6117 | 0.6117 | 0.6117 | 0.6117 |
| p_dead_after_poss | 0.25 | 0.2950 | 0.3859 | 0.4462 | 0.5456 |
| p_flip_after_dead | 0.7 | 0.7333 | 0.5873 | 0.5714 | 0.5587 |
| poss_mean_s | 6.0 | 9.66 | 12.67 | 14.65 | 17.80 |
| dead_mean_s | 10.0 | 20.95 | 20.95 | 20.95 | 20.95 |

q is counted on 258,085 frames per rule, and q per half runs from 0.744 to 0.833. The chain constants come from 315 interior D stretches and 570 to 1,061 interior possessions.

Provenance of each constant:

| constant | v0 | first source | permitted source now | status |
|---|---|---|---|---|
| `target_missing_rate` | 0.407 | baseline_raw's graded rate, pre-kickoff included | `measure`: decode-window rate 0.4110 | changed to `CALIBRATION.window_rate` |
| `prekickoff_missing_rate` | 0.19 | baseline_raw half-2 pre-kickoff, rounded | `measure`: 564 / 2,934 | changed to `CALIBRATION.prekickoff_rate`; inert for scoring |
| generator `dead_bias` worlds | fit-dev (1, 3), sweep (1, 3, 11), score (1) | hand-picked. 1 is the no-information floor. 3 and 11 are the worlds the synthetic-proxy surface was evaluated at. Git records no rationale for 3, and 11 was posed as an extreme. The scaffold's bracket was 0.75 to 11, with 0.75 matched to a public-window missing rate, and the window's dead-to-alive ratio (about 5.2) was then the only real-data evidence. 0.75 never became a CLI default | `measure`: 16 proxy definitions 1.999 to 3.445, median 2.579 | fit-dev (1, 4); sweep (1, 2.6, 4); score (2.6) |
| `q` | 0.78 | the public-window crosstab | Metrica counts 0.7814 to 0.8029 per rule, 0.744 to 0.833 per half | unchanged; 0.78 sits just below the per-rule range and inside the per-half range; no dev sweep has varied `q` |
| `p_flip_after_dead` | 0.7 | public-window D stretches (3 of 4 change team) | dev sweeps 3 to 5 (grid axis {0.55, 0.7, 0.85}); Metrica counts 0.733 raw, 0.559 to 0.587 controlled | unchanged, retained by incumbency: dev cannot separate 0.55 to 0.85 within draw noise (sweep 5), and the controlled counts point lower |
| `alive_share` | 0.6 | Metrica raw labels | Metrica counts 0.6117 | unchanged |
| `p_dead_after_poss` | 0.25 | hand-set | dev sweeps 3 to 5 (grid axis); counts 0.295 to 0.546 | unchanged |
| `poss_mean_s`, `dead_mean_s` | 6, 10 | hand-set | dev sweeps 1 to 5 (grid axes); counts 9.7 to 17.8 and 21.0 | unchanged |
| `temper` | 0.05 | a public-window smoke test of the useful range | dev sweeps 1 to 5 (grid axis; interior in sweeps 1 and 2, lower edge of {0.05, 0.1} in sweeps 3 to 5) | unchanged |
| decoder `dead_bias` belief | 1.0 | design default, argued from a public-window count (66% of GT dead-ball frames show the ball) and the synthetic proxy | dev sweeps (grid axis) | unchanged |
| `fit-dev` grid defaults | q [0.78], p_flip_after_dead [0.7], belief [1.0, 3.0], temper [0.02, 0.05, 0.1, 0.2], rules m0 m2 | q, p_flip_after_dead and belief 1.0 are v0's values (see their rows). The temper grid was set from the smoke test's 0.01 to 0.1 range. m2 exists because raw Metrica spells are much shorter than the public window's (median 7.6 s), though 2 s was not fitted to it | p_flip_after_dead, belief and temper: dev sweeps (grid axes). q: none yet | unchanged |
| reference decoder | v0 over `tier0_v1` | kept on 2026-10-21 on CHALLENGE.md and public-window figures (18% of spells under 3 s, 23 against 17 possessions, spellF1 0.310 against 0.412), while sweep 1's dev result favoured v1 (0.313 against 0.294) | the 30-seed comparison of 2026-10-24 (Dev sweeps): v0 on the controlled conventions (-0.0163 [-0.0325, -0.0002] over games), v1 on m0 and h1p3 | unchanged |
| dev worlds of sweeps 2 to 5 | m0 left out | the same decision | CHALLENGE.md's definition alone supports it (inferred) | unchanged |

The report adopts nothing. Only the provenance text of `params/*.json` changed. Their numeric fields, the decoder defaults and the submission bytes did not. Whether to adopt a counted value is a separate decision. `q`, `p_flip_after_dead` and `temper` in the reference v0 started from the public window. No dev result separates `p_flip_after_dead` or `temper` from their neighbours beyond draw noise, and no dev sweep has varied `q`. The flat decoder belief was argued partly from a public-window count. The case for dropping the m0 world and setting `tier0_v1` aside rests on CHALLENGE.md and on public-window numbers. When it was made, the only dev result favoured v1. The dev result against v1 came later, on the worlds that decision chose. The 30-seed comparison of 2026-10-24 confirms v0 on those worlds and finds v1 ahead on conventions that count touches. The window was also consulted, without setting the value, for poss_mean_s 6 (the smoke test ran at it), alive_share 0.6 (the window's 0.80 was read beside Metrica's 0.55 to 0.68) and marginal decoding (window scores did not separate the decoders). The technical document must disclose all of this. Each params file carries its own disclosure in `provenance.public_window`.

## Open questions and risks

- Answered 2026-10-23: does the real ATD drop the ball more on dead frames than alive ones? Yes, by about 2 to 3.5 times. Crossing the ATD mask with Smart Tagging restarts gives P(missing) 0.7318 in the 5 s before a restart. Against the rest of the decode window outside goals tags (0.3386) that is 2.16, and against team phases clear of set pieces (0.2187) it is 3.35 (`python -m possession measure`). The proxy has two biases it cannot measure. Untagged stoppages sit on the alive side and pull the ratio toward 1. Dead time next to a tagged restart may not stand for all dead time (corners run 1.000 missing, goal kicks 0.478), which can push it either way. Hence the bracket (1, 4) around the point 2.6 rather than the point alone.
- Which label convention does the private GT use? `merge_s` is an axis, not a tuned value. Should we ask the organisers whether a visible-ball goal-kick setup is D or possession, and what hold time the ground truth uses for "controlled"? The controlled rule's `hold_s` brackets it at 2 to 5 s.
- Will Metrica token accuracy (79 to 82% on alive ball-visible frames) and its error burstiness transfer to the challenge (77.8% on the public window)? The surface only brackets dropout, not token noise.
- Should the final submission read the ATD directly instead of the committed `baseline_raw.csv`? Today `baseline_raw.csv` is the only full-match observation and is committed organiser output. "The repo must regenerate the CSV" is satisfied, but the final path should probably be ATD to `Geometry` to `observe`.
- Does tier-0 D help or hurt spellF1? D comes only from mixed-token stretches. Should the grid include a multiplier on `p_dead_after_poss` down to zero until a real dead-ball cue exists?
- Will posterior argmax flicker on real dev tokens? The proxy shows predicted-to-GT spell ratios of 0.45 at a low temper up to 0.97 at the best one, so it under-segments rather than flickers, but the proxy errors are synthetic. Fallbacks, in order: a minimum-run cleanup, a Viterbi decode on the same chain (about 15 lines).
- Metrica file names, the G3 events JSON key names, and "G3 slot team is constant across substitution windows" are from memory and the explorers' notes. First implementation step is to confirm them against the pinned tree before writing the manifest.
- Is three games and six halves enough to pick among 135 configs? `paired_delta` and the per-game rows exist for this, but the worst-case-over-worlds rule may still be noisy. Guess, not measured.
- Should selection average over seeds within each (rule, dead_bias) world before the max-min? The seed is noise, not an unknown like the rule or `dead_bias`, so a plain min over the seed worlds ranks a decoder partly by its unluckiest draw. Re-ranked that way, the sweep 5 grid moves v0 from 30th to 16th (0.3300), with the top 10 within 0.0045, which is inside the draw noise (measured on the sweep 5 grid table). `fit_dev` still takes the plain min over every world. Changing that is a separate decision.
- Byte-for-byte on another machine depends on numpy and the CPU. The design removes BLAS and rounds before argmax, but should the technical document pin the numpy version?
- `pm.spell_overlaps` is O(GT x predicted) pure Python. A pooled dev layout with a flickering decoder could take minutes, hence the guard in `bench.run`. Is a hard limit of 10x acceptable?
- Metrica has no LICENSE and asks for acknowledgement. The technical document needs the attribution and the "external data, explained" line RULES.md requires.

## Next implementation step

Done: every stub, `challenge.load_geometry` included, the sweeps above, the floor comparison and the IDSSE dev source. `make-submission` still reads `baseline_raw.csv`. Switching it to `halves("atd")` leaves the submission bytes unchanged, because the tokens are identical, but it makes the build need the gated data, so that is its own decision. Next, in order: a v0-clean decoder whose constants come from Metrica counts or dev grids instead of the public window; a dead-ball cue (long missing runs, the ball last seen at a line, Smart Tagging restarts); then a richer `Emission` from team-paired features (ball speed and possessor distance, for example). Each is scored against v0 and the floor on all six conventions over 30 seeds, and promoted only on held-out seeds and the game-level interval.
