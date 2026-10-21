"""Label every frame of a half H/A/D. A decoder is `Emission` + a small hidden Markov chain.

    Half --Emission.loglik--> float [n, 3] evidence per label --forward-backward--> P(label | all evidence)
         --argmax--> codes

The seam is the evidence matrix. The chain below knows nothing about balls, teams, slots or Metrica;
an Emission knows nothing about durations or kickoffs. Tier-0 (nearest-team token + ball-visibility
mask) is one Emission; the ATD-era feature model is another and nothing else here changes.

THE DECISIONS (measured on synthetic truth + the REAL baseline_raw dropout masks during the design
bakeoff; a labelled proxy, to be re-run on the Metrica dev set):

  * two decode rules over ONE chain, chosen per config (`DecoderParams.decode_rule`) and settled on the
    dev set, not here:
      "marginal" (default): forward-backward, argmax of each block's label posterior. Robust to a
        mistuned temper; on the proxy MAP at low temper collapsed into the flat-evidence D state
        (spellF1 0.02 vs 0.35), while at a tuned temper the two were within 0.02.
      "map": exact most-likely segmentation under shifted-geometric durations with a hard minimum
        (`min_poss_frames`, `min_dead_frames`), by prefix sums in O(n K^2). Equal to Viterbi on the
        expanded chain-state HMM to 7e-14 (bakeoff probe); 0.21 s per 79k-frame half at stride 1.
    "marginal" supports only min durations of 1 (a minimum needs the expanded chain; measured worth
    +0.006..0.008 at 1 s and negative from 2 s under posterior decoding, so it is not offered).
  * D remembers who last had the ball (D_after_H, D_after_A). A stoppage then carries the flip prior
    (3 of the 4 public-window D stretches change team); both D states emit the label D.
  * missing ball = "no evidence", never "dead". Only the explicit `dead_bias` belief may make a missing
    frame lean D, and its default is 1.0 (flat).
  * the evidence is TEMPERED. 25 frames/s of nearest-team tokens are strongly autocorrelated (a pressing
    opponent stays nearest for seconds); summing them as independent makes the chain ignore its own
    switch prior. `temper` (alpha) scales summed log-evidence, and is the main knob the grid tunes.
    On the real baseline_raw tokens the useful range is 0.01..0.1 (public-window smoke test, untuned,
    spellF1 0.41-0.47 across it); iid synthetic tokens wanted 0.2-0.8, which is the point of tuning on
    geometry-derived dev tokens whose errors are bursty.

Decoding runs per half, on blocks of `stride` frames (evidence summed per block, partial last block
allowed), then upsampled. Measured: K = 4 forward-backward costs 0.31 s per 79k-frame half at stride 1
and 0.06 s at stride 5, so a 100-config x 3-world x 6-half grid is minutes, not hours.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Protocol

import numpy as np
from numpy.typing import NDArray

from .half import A, D, FPS, H, Half

N_STATES = 4  # H, A, D_after_H, D_after_A
STATE_LABEL = np.array([H, A, D, D], dtype=np.int8)


class Emission(Protocol):
    """Per-frame evidence for each label. The ONLY thing a decoder needs from observations."""

    def loglik(self, half: Half) -> NDArray[np.float32]:
        """float32 [n, 3], natural-log likelihood of frame i's observation under H, A, D, up to a
        per-frame constant. Rows with no evidence must be all-equal (flat), never NaN."""
        ...


@dataclass(frozen=True, slots=True)
class Tier0Emission:
    """Evidence from `Half.nearest_team` alone: token in {HOME, AWAY, none}.

    Model, per frame with label k in {H, A, D}:
        P(none | k)         = m_k
        P(token t | k)      = (1 - m_k) * T[k, t]
    T is team-symmetric: T[H, HOME] = T[A, AWAY] = q, T[H, AWAY] = T[A, HOME] = 1 - q, T[D, .] = (.5, .5).
    m_H = m_A = m_alive, m_D = dead_bias * m_alive, with m_alive solved per half from the half's
    OBSERVED missing rate r over [kickoff, n) and a prior alive share a0:
        r = m_alive * (a0 + (1 - a0) * dead_bias)        (clipped to 0.98)
    dead_bias = 1.0 makes every missing frame's row flat. dead_bias != 1 is a BELIEF about the real ATD
    that the bench scores against every generator world (bench.surface); it is never fitted to the dev
    set, because fitting it there just reads back the generator's own setting.

    q:           P(token == label's team | alive, ball seen). fit() by counting; Metrica 0.79-0.82,
                 public window 0.778.
    dead_bias:   rho_hat. Belief, default 1.0.
    alive_share: a0, prior over the alive share of the half. 0.6 (Metrica 0.55-0.68, public window 0.80).
    """
    q: float = 0.78
    dead_bias: float = 1.0
    alive_share: float = 0.6

    def loglik(self, half: Half) -> NDArray[np.float32]:
        # TODO: seen = half.nearest_team >= 0; r = 1 - seen[kickoff:].mean()
        # TODO: m_a = min(r / (a0 + (1 - a0) * rho), 0.98); m_d = min(rho * m_a, 0.98)
        # TODO: ll = empty [n,3]; ll[~seen] = log([m_a, m_a, m_d])
        #       for t in (HOME, AWAY): ll[tok == t] = log(T[:, t]) + log([1-m_a, 1-m_a, 1-m_d])
        raise NotImplementedError

    @staticmethod
    def fit(pairs: Iterable[tuple[Half, NDArray[np.int8]]], base: "Tier0Emission") -> "Tier0Emission":
        """q by counting on graded alive frames with a visible ball (labels in {H, A}, X ignored),
        pooled over teams and halves, Laplace-smoothed (+1/+1). dead_bias and alive_share pass through
        from `base` untouched."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class DecoderParams:
    """Everything the chain needs. Counts-derived fields are filled by `fit`, the rest by the grid.

    temper:             alpha, scale on summed log-evidence. Grid {0.01, 0.02, 0.05, 0.1, 0.2}.  (grid)
    poss_mean_s:        mean H/A spell in seconds; geometric, hazard 1 / (poss_mean_s * FPS / stride). (grid)
    dead_mean_s:        mean D stretch in seconds.                                              (grid)
    p_dead_after_poss:  P(next segment is D | a possession ends).                               (fit)
    p_flip_after_dead:  P(next possession is the OTHER team | a D stretch ends).                (fit)
    stride:             frames per decode block. Speed knob: 5 by default, 1 allowed (0.31 s per half).
    decode_rule:        "marginal" | "map", see the module docstring.                         (grid)
    min_poss_frames:    hard minimum H/A segment length in frames; "map" only, 1 = none.        (grid)
    min_dead_frames:    hard minimum D segment length in frames; "map" only, 1 = none.          (grid)

    Under "map" a segment of state s lasts min + Geometric frames with mean poss_mean_s / dead_mean_s
    (shifted geometric), so mean > min is required. Minimums are converted to blocks by ceil(min / stride).

    H/A symmetric by construction: no home-advantage prior, and no swap of tokens can change the answer.
    Provenance of every fitted number is recorded in the params JSON, not here.
    """
    temper: float = 0.05
    poss_mean_s: float = 6.0
    dead_mean_s: float = 10.0
    p_dead_after_poss: float = 0.25
    p_flip_after_dead: float = 0.7
    stride: int = 5
    decode_rule: Literal["marginal", "map"] = "marginal"
    min_poss_frames: int = 1
    min_dead_frames: int = 1


@dataclass(frozen=True, slots=True)
class Decoded:
    """codes: int8 [n] in {0,1,2}, never X. posterior: float32 [n, 3] P(H), P(A), P(D) given all
    evidence in the half (tempered). Frames [0, kickoff) are D with posterior (0, 0, 1)."""
    codes: NDArray[np.int8]
    posterior: NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Decoder:
    """A fitted, immutable, JSON-serialisable decoder. `decode` is a pure function of (self, half)."""
    emission: Tier0Emission  # widen to a union when the ATD-era emission exists
    params: DecoderParams

    def decode(self, half: Half) -> Decoded:
        """Label one half. Deterministic: float64 throughout, no RNG, no BLAS in the loop.

        Contract, in the order it is applied:
          1. frames [0, half.id.kickoff) are D by rule (the challenge grades half 2's first 2934 frames
             as D; an X head would be back-filled with the first label and become a false 117 s spell).
          2. decode [kickoff, n) from a uniform start over {H, A}.
          3. codes = argmax over round(posterior, 9). The rounding makes exact symmetric ties (a flat
             block at the start of a half) resolve to the lower label on every machine instead of on
             1-ulp noise.
        """
        # TODO: ev = self.emission.loglik(half)[kickoff:].astype(float64)
        # TODO: E = temper * np.add.reduceat(ev, np.arange(0, m, stride), axis=0)        # [nb, 3]
        # TODO: "marginal": post_blocks = _forward_backward(E, _chain(self.params))      # [nb, 3]
        #       "map":      labels_blocks = _map(E, self.params); posterior = one-hot of the path
        # TODO: upsample by repeat(stride)[:m]; prepend D rows for [0, kickoff); argmax of round(., 9)
        raise NotImplementedError

    def save(self, path: str | Path, provenance: Mapping[str, object]) -> Path:
        """{"emission": {"kind": "tier0", ...}, "params": {...}, "provenance": {...}} with sorted keys
        and fixed float formatting, so the committed file and the submission it produces are both
        byte-stable. Numbers only: no data, no tracking, safe to commit (params/*.json)."""
        raise NotImplementedError

    @staticmethod
    def load(path: str | Path) -> "Decoder":
        """Boundary: parse + validate ranges (0 < q < 1, 0 < p < 1, temper > 0, stride >= 1)."""
        raise NotImplementedError


def fit(pairs: Iterable[tuple[Half, NDArray[np.int8]]], base: Decoder) -> Decoder:
    """Supervised counts, no EM. Fills the (fit) fields of `base` and leaves the (grid) fields alone.

    pairs: (half, labels) with labels int8 [n] in {0..3}; X (ungraded) frames are ignored, so the
    public window can be passed too (for a consistency read, never for selection).
      q                 <- Tier0Emission.fit
      p_dead_after_poss <- (# possession segments followed by D) / (# possession segments followed by anything), +1/+2 smoothing
      p_flip_after_dead <- (# D stretches whose next possession is the other team than the previous one) / (# D stretches
                           with a possession on both sides), +1/+2 smoothing. H/A pooled (symmetry).
    Durations are NOT fitted: Metrica spells are convention-biased (merge_s, ~30% under 2 s) while the
    challenge's are not, so poss_mean_s / dead_mean_s are grid knobs scored across merge_s worlds.
    """
    # TODO: segments per labelled half via run-length encoding of non-X runs. A segment touching an X
    #       boundary or the end of a half is truncated: count its transition only if the transition itself
    #       is observed, so edge runs never bias p_dead_after_poss / p_flip_after_dead.
    raise NotImplementedError


# --- internals: kept private, exercised through Decoder.decode -----------------------------------------

@dataclass(frozen=True, slots=True)
class _Chain:
    """trans float64 [4,4] row-stochastic per block; init float64 [4] (0.5, 0.5, 0, 0)."""
    trans: NDArray[np.float64]
    init: NDArray[np.float64]


def _chain(p: DecoderParams) -> _Chain:
    """States 0=H 1=A 2=D_after_H 3=D_after_A. With blocks of `stride` frames:
        hp = 1 / (poss_mean_s * FPS / stride)     hd = 1 / (dead_mean_s * FPS / stride)     (clipped to <= 0.5)
        H -> H 1-hp ;  H -> D_after_H hp*p_dead ;  H -> A hp*(1-p_dead)
        D_after_H -> D_after_H 1-hd ;  -> H hd*(1-p_flip) ;  -> A hd*p_flip
        A and D_after_A mirror those.
    """
    raise NotImplementedError


def _forward_backward(E: NDArray[np.float64], chain: _Chain) -> NDArray[np.float64]:
    """Scaled forward-backward on block evidence E [nb, 3] -> label posteriors [nb, 3].

    The per-label evidence is broadcast to states through STATE_LABEL. Scaled in the probability
    domain (K = 4 makes log-domain pointless):
    """
    # TODO: Ek = exp(E - E.max(axis=1, keepdims=True))[:, STATE_LABEL]              # [nb, 4], row max removed
    # TODO: alpha[0] = init * Ek[0]; alpha[0] /= alpha[0].sum()
    #       alpha[t] = (alpha[t-1][:, None] * trans).sum(0) * Ek[t]; alpha[t] /= alpha[t].sum()
    # TODO: beta[-1] = 1; beta[t] = (trans * (Ek[t+1] * beta[t+1])[None, :]).sum(1); beta[t] /= beta[t].sum()
    # TODO: gamma = alpha * beta; gamma /= gamma.sum(1, keepdims=True)
    #       post = stack([gamma[:, 0], gamma[:, 1], gamma[:, 2] + gamma[:, 3]], axis=1)
    #       (explicit elementwise sums, not `@`: no BLAS path, same bits on every machine)
    raise NotImplementedError


def _map(E: NDArray[np.float64], p: DecoderParams) -> NDArray[np.int8]:
    """Exact MAP segmentation of block evidence E [nb, 3] -> label codes [nb] in {H, A, D}.

    Same four states and switch probabilities as `_chain` (H, A, D_after_H, D_after_A; D states share
    the D evidence column). Segment of state s lasts k_s + Geometric blocks, k_s = ceil(min / stride),
    continuation probability c_s = (mean_s - k_s) / (mean_s - k_s + 1) with mean_s in blocks. Start at
    the kickoff in H or A with 0.5 each. Prefix sums C [nb+1, 4] make "a fresh segment of state c over
    [s, t]" cost C[t+1, c] - C[s, c], so the minimum is one lookup instead of k chain states:

        t = 0:  V[c] = log_pi[c] + E[0, c]
        t >= 1: cont = V_prev[c] + log c_c + E[t, c]
                s = t - k_c + 1; new = ent[s][c] + C[t+1, c] - C[s, c]  (s >= 1)
                take new only if new > cont (ties continue: deterministic, latest switch)
                ent[t+1][c] = max over predecessors q of V_t[q] + log(1 - c_q) + log T[q -> c]
        end:    best of V at nb-1 and of the right-censored tails ent[s][c] + C[nb, c] - C[s, c].
        back:   hop segment to segment through the stored segment starts and entry predecessors.

    Model constants (log tables) are rounded to 1e-12 before use so an ulp of libm drift cannot move a
    near-tie boundary. Port of the bakeoff's probe; selfcheck.map_equals_expanded_viterbi pins it.
    """
    raise NotImplementedError
