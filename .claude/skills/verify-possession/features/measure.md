# Measure the match observation

`measure` prints match-wide aggregates that the dropout generator's and the decoder's constants rest on. It reports the tactical ATD ball mask by zone, the Smart Tagging inventory, ball-missing rates by stratum and by offset from a restart, the `dead_bias` each dead-ball proxy implies, the ATD and `baseline_raw` run pools, and the players tracked while the ball is missing. It then counts the decoder constants on the Metrica labels next to the values in `params/tier0_v0.json`. It takes no flags, writes no file, and never reads the public ground truth. `selfcheck` pins its counts and checks `dropout.CALIBRATION` against them.

## Sub-features

- `measure-mask` prints the ball mask by zone, including the decode-window rate the generator targets.
- `measure-tags` prints the Smart Tagging inventory and the time-base check.
- `measure-rho` prints the strata, the offset profile and the proxy sweep, with the purity and calibration lines.
- `measure-pool` shows that the ATD and `baseline_raw` run pools are identical.
- `measure-coverage` prints the players tracked while the ball is missing.
- `measure-constants` prints the decoder constants counted on the Metrica labels.
- `measure-nodata` prints one skip line per absent data group and exits `0`.

## How to get to it (user POV)

- Run `.venv/bin/python -m possession measure`.

## Driving it with run.sh

Preconditions:

- The doctor reports `tactical ATD and Smart Tagging 3/3 files` and `Metrica sample data 9/9 files`.
- `EV` is this run's evidence folder, `data/derived/verify/$RUN_ID` (or under `$MTAH_DATA_DIR/derived/verify/$RUN_ID`).

- **Measure.** Run `$V/run.sh "$RUN_ID" measure .venv/bin/python -m possession measure`. Exit code is `0` and `measure.err` is empty. In `measure.out`:
  - `measure-mask`: the `window both` row shows frames `155923`, missing `64079`, rate `0.4110`, and `146` missing and `145` present runs. The `pre-kickoff 2` row shows `2934`, `564` and `0.1922`. The line under the table reads `generator defaults (DropoutParams): target_missing_rate 0.4110, prekickoff_missing_rate 0.1922`.
  - `measure-tags`: the lines `638 instances, 14 codes; time base agrees: the kick off (start) set pieces contain rows 11185 and 113742` and `82.3% of graded rows lie under a tag` are present.
  - `measure-rho`: the `restart lead 5 s, every kind` row shows `7125`, `5214`, `0.7318` and `1.8498`. Under the sweep table, the lines read `headline 1.8498; 16 definitions 1.6966..2.0605, median 1.8074; restart kinds at lead 5 s 1.2073..2.5278`, `purity: world 11 shows the median only if 8.1% of proxy rows are dead ball; at purity 0.35 the median corrects to 3.31`, and `dropout.CALIBRATION: dead_bias 1.8 inside the 16-definition spread: yes; bracket 1..3 holds all 21 estimates: yes`.
  - `measure-pool`: the `atd` and `baseline_raw` rows both show `146`, `145`, `155923`, `64079` and `True`.
  - `measure-coverage`: the `missing` rows show `players_mean` `18.2335` for half 1 and `20.0988` for half 2.
  - `measure-constants`: the `q` row reads `0.78 0.8029 0.7977 0.7927 0.7814`, and the `p_flip_after_dead` row reads `0.70 0.7333 0.5873 0.5714 0.5587`. The `support` table shows `dead_flips` `231`, `185`, `180` and `176` of `315` `dead_segments`.
- **Line check.** Run `$V/run.sh "$RUN_ID" measure-grep grep -c -x -e "generator defaults (DropoutParams): target_missing_rate 0.4110, prekickoff_missing_rate 0.1922" -e "dropout.CALIBRATION: dead_bias 1.8 inside the 16-definition spread: yes; bracket 1..3 holds all 21 estimates: yes" "$EV/measure.out"`. stdout reads `2`.
- **No data.** Run `$V/run.sh "$RUN_ID" measure-nodata env MTAH_DATA_DIR=/nonexistent .venv/bin/python -m possession measure`. Exit code is `0`. stdout has two skip lines, `tactical sections  skip: no ATD or Smart Tagging under /nonexistent/tactical (set MTAH_DATA_DIR)` and `constants  skip: no Metrica sample data under /nonexistent/metrica_sample (set MTAH_DATA_DIR or run fetch-metrica)`.

## Gotchas

- There are two gates. The real-match sections need the three tactical files, and the constants need the Metrica sample. Each group skips on its own, so one missing folder never hides the other group.
- The output is derived from gated match data. It holds only aggregates, but keep `measure.out` in the evidence folder under `data/` and never commit it. Quote only the aggregate lines this file lists.
- `measure` has no flags. To change a proxy definition, change `measure.SWEEP` or `measure.KIND_PROXIES` and its pin in `selfcheck.measure_pins_calibration` in the same commit.
- The decoder constants are a report. Nothing reads them back into `params/` or a default.
- A run takes about 4 s.
