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
python -m possession fit-dev --seed 0 --merge-s 0 1 2 --dead-bias 1 3 11 --out params/tier0_v1.json
python -m possession score --params params/tier0_v1.json --dev --public     # table; writes data/derived/runs/
python -m possession make-submission --params params/tier0_v1.json --out evaluation/results/possession_v1.csv
python evaluation/run_evaluation.py --bootstrap 1000    # existing scorer, unchanged, scores the CSV on the public window
```

`make-submission` reads `evaluation/results/baseline_raw.csv` and the params JSON. It uses no RNG and no Metrica files, so it reproduces the CSV byte for byte on a clean checkout. `fit-dev` is the only command that needs Metrica, and its product is a small JSON of numbers.

Python, score a decoder on three dev games, the pooled dev set and the public window. Two calls:

```python
from possession import bench, decoder

cases = bench.dev_cases(bench.DevSpec()) + [bench.public_case()]   # dev_g1, dev_g2, dev_g3, dev_pooled, public
table = bench.run({"v1": decoder.Decoder.load("params/tier0_v1.json")}, cases)
print(table[["model", "case", "spell_f1", "macro_f1", "n_pred_spells", "n_gt_spells"]])
```

Python, ask the question the real ATD cannot yet answer, "does it drop the ball more on dead frames?", as a number per decoder choice:

```python
from possession import bench, decoder, dropout

base = decoder.Decoder.load("params/tier0_v1.json")
worlds = {rho: bench.dev_cases(bench.DevSpec(dropout=dropout.DropoutParams(dead_bias=rho)))
          for rho in (1, 3, 11)}
print(bench.surface(base, worlds, beliefs=(1, 3, 11)))   # rows generator dead_bias, cols decoder belief, last row = min over worlds
```

Python, the ATD plug-in. This is the whole change when the gated data arrives:

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
| `score.py` | the only import of `pm` | `evaluate`, `write_submission`, `read_codes`, `matched_flags` | import style, range guard, assembly, newline and rename discipline |
| `challenge.py` | BAR-ATH: blocks, kickoffs, the tier-0 token, baseline_raw, the ATD seam | `halves(source)`, `layout`, `observe`, `nearest_team` | the "D means missing" translation, the ATD grammar |
| `metrica/` | the sample data | `fetch`, `load`, `RuleV2` | pinned URLs, sha256, two file formats, label rule v2, native-NaN fill |
| `dropout.py` | challenge-ification | `challengeify`, `DropoutParams` | rate solving, renewal masks, RNG streams |
| `decoder.py` | evidence to labels | `Decoder.decode/save/load`, `fit`, `Tier0Emission`, `DecoderParams` | chain, forward-backward, blocks, kickoff, tie rounding |
| `bench.py` | scoring problems and the selection protocol | `dev_cases`, `public_case`, `run`, `surface`, `fit_dev`, `paired_delta` | which cases exist, worlds, max-min |
| `selfcheck.py` | the invariants as runnable checks | `run` | |

This deliberately departs from the grounding's stage-shaped map (`halves / features / decode / sources / devset / submit / score`). Load, featurise, decode and submit are execution order, not ownership, and each stage would repeat the half bundle's rules (per `model-the-domain`: "execution order is not ownership"). Here, one module owns each body of knowledge. The longest user-visible chain is `bench -> dropout -> challenge` (three files), and `bench -> metrica -> metrica.rule` for labels.

### Data structures first

- `Geometry` (Level A): `ball_xy float32 [n,2]` metres NaN-for-unobserved, `players_xy float32 [n,S,2]` NaN-for-empty-slot, `slot_team int8 [S]`, `pitch_m`. Slots are anonymous. S=46 for the challenge, 22 to 28 for Metrica.
- `Half` (Level B): `HalfId(match, half, kickoff)`, `nearest_team int8 [n]` in {-1,0,1}, optional `Features`. This is the decoder's whole input. `-1` means no evidence. It is a mask, never a dead-ball marker, and the type has no label field for a dead ball to sneak into.
- `CleanHalf`: `Geometry` with a fully observed ball, plus `labels int8 [n]` in {0,1,2}, plus provenance. Native NaN are filled upstream, so injected dropout is the only missingness a decoder can ever see.
- `Layout`/`Block`: the only owner of origins. X exists only outside blocks. Invariant: at least 500 X rows before, between and after blocks, so `pm.valid_runs` returns exactly one run per half. The challenge layout is built from `games.half_video_blocks`, the dev layout is `Layout.synthetic`.
- `Case`: layout, halves, a scorer-length `gt` assembled from labels (derived, never stored twice), provenance.
- `Decoder`: frozen `(Tier0Emission, DecoderParams)`, serialisable to JSON.

Geometry is a separate type from `Half` on purpose. `Half` is what both the tier-0 file (no geometry, ever) and the future ATD path (geometry) can supply. Putting geometry on `Half` as an optional field would be "sometimes geometric", which forces an `if` into the decoder (per `type-system-discipline`, no bags of optional fields). `Half.features` is the one reserved optional and it is always `None` in the first implementation. I keep it because the task asks the shape to show what the ATD must produce. Its contract is in the `Features` docstring.

### The decoder

```
Half --Emission.loglik--> float [n,3] evidence per label --forward-backward on 4 states--> P(H,A,D | all evidence) --argmax--> codes
```

The seam is the evidence matrix. The chain knows nothing about balls or teams. An `Emission` knows nothing about durations or kickoffs. Tier-0 is one `Emission`. The ATD-era feature model is another, and nothing else moves (per `boundary-discipline`, general mechanism inside and source-specific policy at the edge).

Four states: H, A, D_after_H, D_after_A. Both D states emit label D. D remembers the last possessor so a stoppage can carry a flip prior (3 of the 4 public-window D stretches change team, inferred from the segment table, n=4). Durations are geometric with per-class means. Evidence is tempered by a scalar alpha. Frames [0, kickoff) are D by rule. A missing ball is flat evidence unless the explicit `dead_bias` belief is set. Decoding runs on blocks of 5 frames.

Interface depth: `Decoder.decode(half)` is the whole decoding API. It hides the chain, scaling, block aggregation, kickoff handling and tie rounding. The caller supplies a `Half` and receives codes plus a posterior.

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

### The Metrica dev set

`metrica.load(RuleV2(merge_s))` returns six `CleanHalf`. `dropout.challengeify(clean, DropoutParams, seed)` returns six `Half`. Everything shaping a world is in `DevSpec`, namely `merge_s`, `dead_bias`, target rate, seed and fill rule.

- **Parse raw, no kloppy.** Two format parsers behind one `RawGame`. Coordinates to metres, no y flip. Periods split on the `Period` column. G3 slot team is asserted constant across substitution windows.
- **Labels from events only (rule v2).** Pure function `label_period(events, frame0, n, rule)`. Dead openers, restart closers, restart fallback, owner timeline, optional merge, all in the TODO pseudocode. Acceptance numbers are the explorers' (alive share 55.1/58.4/67.9%, raw spells 364/322/387).
- **Pre-kickoff is D, post-whistle is trimmed.** A half block starts at the period's first tracking frame and ends at the last event end plus one. Frames before kickoff are D. This mirrors the challenge's graded half 2 (2,934 D frames) and exercises the kickoff rule in dev. An X head would be back-filled by `pm.fill_abstentions` into a false spell, so D it is.
- **Native NaN fill.** Default `hold` (forward-fill, back-fill the head). It is a parameter, not an open question. The reason is that `linear` gives a dead ball a constant velocity that a ball-speed feature would read as live play, which is a different leak.
- **Dropout.** Alternating renewal process. Missing runs are resampled from baseline_raw's 150 real runs, present runs from its 149 real runs, scaled by the closed form `c = E[m](1-r)/(r E[p])` so the stationary rate is `r`. One mask for alive frames, one for dead frames, selected by label. `solve_rates(a, target, rho, cap)` solves both constraints given the half's alive share `a`. They are `a*p_alive + (1-a)*p_dead = 0.407` and `p_dead = rho * p_alive`, with a cap and a loud failure if unreachable. Pre-kickoff is its own stratum at 0.19 (564 of 2934 missing in the real half-2 stretch). A prototype of this generator (**measured**, `e2_dead_bias_surface.py`) realised an overall rate of 0.39 to 0.43 at target 0.407, and at rho 3 a P(missing | dead) of 0.83 and a P(missing | alive) of 0.27.
- **Identity.** Not simulated. `challenge.nearest_team` reduces over slots per frame, so identity-freedom is a tested property (`selfcheck.permutation_invariance`). `fragment_slots` is a stub marking the hook for the ATD era.
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

Wrongly believing missingness means dead costs 0.10, and wrongly ignoring it costs 0.09 in the dead-heavy world, so the surface is informative and asymmetric. The selection rule is therefore max-min over worlds, ties by mean. Worlds are `merge_s` times `dead_bias` (both unknown for the real match). The `dead_bias` key is the requested ratio. Above roughly 8 the 0.98 per-state cap binds on high-alive halves and the effective ratio saturates (G3, alive share 0.68, at 11 gives about 7; the proxy's 78%-alive truth gave 4.2). The realised rates are recomputed into each case's provenance, so a table never reports a ratio the data did not have. `dead_bias` is never fitted on the dev set, because fitting it there reads back the generator's own setting. Counts-derived parameters (`q`, `p_dead_after_poss`, `p_flip_after_dead`) are fitted by supervised counts with Laplace smoothing, no EM. The grid covers what counts cannot give (alpha, the two mean durations, the belief). Decode costs about 0.06 s per half at stride 5, so the 135-config by 3-world grid is a few minutes (**measured** decode time, grid size by arithmetic). `paired_delta` bootstraps the GT possessions two decoders share before anyone believes a gap under 0.04.

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

`challenge.load_geometry()` must return, per half, a `Geometry`: `ball_xy` and `players_xy` in metres (normalised times 105.3 and 68.0), NaN for `N` groups, S=46, `slot_team` from the XML `<Player teamId>` order with the first `<Team>` as home, rows equal to ATD `frame_id - 1` over `games.half_video_blocks`. `observe` turns it into a `Half`. The regression gate is that `observe` reproduces `baseline_raw.csv` on at least 99.99% of frames (exact equality is not promised, float32 can flip a near-tie). Richer evidence is `Features` computed in `observe`, team-paired and slot-order invariant, with ball-free columns that stay defined during dropout. Those ball-free columns are where the ATD era can beat tier-0, because a dropout block is 10 s of zero evidence today. Smart Tagging set-piece windows are a second source for the same `Features` contract.

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
- From the fable sketch, fitting ignores truncated edge runs (`decoder.fit`).

Rejected: boundary refinement (`_refine` / centring, measured at +0.000..0.017), posterior abstention and spell absorption (measured at noise or macroF1-only), the evidence-prior registries and binned naive-Bayes emission (speculative before any feature exists), the npz dev cache (invalidation surface), 46-slot tracklet simulation (needs the gated ATD to calibrate; tier-0 tokens cannot see it). Deferred: an explicit `ball_seen` mask on `Half` (needed once ball-only features exist), the turnover-biased dropout world.

## Tradeoffs accepted

- We accept that tier-0 barely predicts D (0 to 7% of window frames against 19.6% in GT, **measured** on untuned runs) in exchange for never teaching the decoder that a missing ball means dead ball. Dead-ball detection waits for features.
- We accept that posterior-argmax carries no duration guarantee in exchange for robustness to a mistuned temper and for centred switches. `bench.run` guards the predicted-to-GT spell ratio so flicker shows up immediately.
- We accept one scalar temper in place of a model of burst-correlated token errors (a clean/noisy regime in the emission) in exchange for a four-state chain. The dev tokens are geometry-derived and bursty, so tuning the scalar there is the cheap proxy.
- We accept geometric durations that are tuned, not fitted, in exchange for not baking Metrica's event convention (30% of raw spells under 2 s) into the challenge decoder.
- We accept H/A symmetry (no home advantage) in exchange for a decoder that cannot be fooled by a team-label swap and that three games cannot mis-estimate.
- We accept a stationary dropout generator that ignores play and camera in exchange for a bracketing sweep (`dead_bias` 0.75 to 11) that does not pretend to know the real dependence.
- We accept `hold` fill, which gives a dead ball a stationary position, in exchange for avoiding a constant-velocity dead ball. A ball-speed feature may still read "stationary" as a weak dead cue.
- We accept block decoding at stride 5 (switches quantised to 5 frames, tolerance in the scorer is 12) in exchange for a 5x faster grid. `stride=1` stays one parameter away.
- We accept committing fitted numbers (`params/*.json`) derived from external public data in exchange for a submission path that never touches Metrica. The refit needs the fetch.
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

## Open questions and risks

- Does the real ATD drop the ball more on dead frames than alive ones? The public window gives P(missing | GT D) 0.34 and P(missing | GT alive) 0.065, which cannot both hold match-wide (overall 0.407). Who answers it, and can Smart Tagging set-piece windows be crossed with the ATD mask once the data lands?
- Which label convention does the private GT use? `merge_s` is an axis, not a tuned value. Should we ask the organisers whether a visible-ball goal-kick setup is D or possession, and whether "controlled possession" merges quick RECOVERY/PASS alternations?
- Will Metrica token accuracy (79 to 82% on alive ball-visible frames) and its error burstiness transfer to the challenge (77.8% on the public window)? The surface only brackets dropout, not token noise.
- Should the final submission read the ATD directly instead of the committed `baseline_raw.csv`? Today `baseline_raw.csv` is the only full-match observation and is committed organiser output. "The repo must regenerate the CSV" is satisfied, but the final path should probably be ATD to `Geometry` to `observe`.
- Does tier-0 D help or hurt spellF1? D comes only from mixed-token stretches. Should the grid include a multiplier on `p_dead_after_poss` down to zero until a real dead-ball cue exists?
- Will posterior argmax flicker on real dev tokens? The proxy shows predicted-to-GT spell ratios of 0.45 at a low temper up to 0.97 at the best one, so it under-segments rather than flickers, but the proxy errors are synthetic. Fallbacks, in order: a minimum-run cleanup, a Viterbi decode on the same chain (about 15 lines).
- Metrica file names, the G3 events JSON key names, and "G3 slot team is constant across substitution windows" are from memory and the explorers' notes. First implementation step is to confirm them against the pinned tree before writing the manifest.
- Is three games and six halves enough to pick among 135 configs? `paired_delta` and the per-game rows exist for this, but the worst-case-over-worlds rule may still be noisy. Guess, not measured.
- Byte-for-byte on another machine depends on numpy and the CPU. The design removes BLAS and rounds before argmax, but should the technical document pin the numpy version?
- `pm.spell_overlaps` is O(GT x predicted) pure Python. A pooled dev layout with a flickering decoder could take minutes, hence the guard in `bench.run`. Is a hard limit of 10x acceptable?
- Metrica has no LICENSE and asks for acknowledgement. The technical document needs the attribution and the "external data, explained" line RULES.md requires.

## Next implementation step

Implement `half.py`, `score.py`, `challenge._halves_from_baseline_raw` and the `decoder.py` forward-backward, then make `selfcheck.oracle_scores_one`, `baseline_raw_round_trip` and `decoder_known_answer` pass, which yields a valid 199,319-row CSV from `baseline_raw.csv` before any Metrica code exists.
