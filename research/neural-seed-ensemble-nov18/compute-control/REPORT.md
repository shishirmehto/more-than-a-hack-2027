# Matched-update control:1x1800 versus3x600

Same full data, architecture, optimizer, seed, decoder and evaluation; only training duration changes. Each1800-step run exactly reproduced its frozen600-step checkpoint before continuing Adam. Three seed replications; every result reported, no seed selection.

| Held-out tracker | Single600 seed98117 | Single1800 seed98117 | Mean3 singles1800 | Ensemble3x600 |
|---|---:|---:|---:|---:|
| idsse | 0.547415 | 0.551708 | 0.550582 | 0.548239 |
| metrica | 0.648675 | 0.678127 | 0.677821 | 0.650548 |
| skillcorner | 0.367492 | 0.343457 | 0.346376 | 0.370739 |

## Interpretation limits

This matches total gradient updates, not exact wall time or every possible optimized learning-rate schedule. The ensemble costs about3x model evaluations at inference. Seed means and the predeclared seed98117 contrast are both reported; the best observed seed is not selected. These are reused external tracker results and inherited baseline heads remain fixed. No PFF or challenge-label access, no new submission candidate selected.

Per-game/seed results, training timings and exact checkpoint assertions are in rows.json and fits.json. Descriptive game-paired intervals are in paired-comparison.json.
