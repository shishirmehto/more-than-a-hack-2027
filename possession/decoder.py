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
        expanded chain-state HMM to 7e-14 (bakeoff probe); 0.17-0.20 s per 79k-frame half at stride 1.
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
allowed), then upsampled. Measured on the baseline_raw halves: K = 4 forward-backward costs 0.08 s per
79k-frame half at stride 1 and 0.015 s at stride 5, so a 100-config x 3-world x 6-half grid is minutes,
not hours.
"""
from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Mapping, Protocol

import numpy as np
from numpy.typing import NDArray

from .half import A, D, FPS, H, X, Half

N_STATES = 4  # H, A, D_after_H, D_after_A
STATE_LABEL = np.array([H, A, D, D], dtype=np.int8)
_DH, _DA = 2, 3

# Missing-rate clip for Tier0Emission. The floor keeps log(m) finite on a half whose decode window
# has no missing frame (its pre-kickoff rows may still be missing and are part of loglik's output).
_M_FLOOR, _M_CAP = 1e-6, 0.98


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
        tok = half.nearest_team
        r = float((tok[half.id.kickoff:] < 0).mean())
        rho, a0, q = self.dead_bias, self.alive_share, self.q
        m_a = min(max(r / (a0 + (1 - a0) * rho), _M_FLOOR), _M_CAP)
        m_d = min(max(rho * m_a, _M_FLOOR), _M_CAP)
        seen = np.log([1 - m_a, 1 - m_a, 1 - m_d])
        table = np.array([                                   # row = token + 1: NO_TEAM, HOME, AWAY
            np.log([m_a, m_a, m_d]),
            np.log([q, 1 - q, 0.5]) + seen,
            np.log([1 - q, q, 0.5]) + seen,
        ])
        return table[tok + 1].astype(np.float32)

    @staticmethod
    def fit(pairs: Iterable[tuple[Half, NDArray[np.int8]]], base: "Tier0Emission") -> "Tier0Emission":
        """q by counting on graded alive frames with a visible ball (labels in {H, A}, X ignored),
        pooled over teams and halves, Laplace-smoothed (+1/+1). dead_bias and alive_share pass through
        from `base` untouched."""
        hit = total = 0
        for half, labels in pairs:
            tok = half.nearest_team
            if labels.shape != tok.shape:
                raise ValueError(f"labels {labels.shape} do not match half {tok.shape}")
            use = ((labels == H) | (labels == A)) & (tok >= 0)
            total += int(use.sum())
            hit += int((tok[use] == labels[use]).sum())  # HOME == H, AWAY == A
        return dataclasses.replace(base, q=(hit + 1) / (total + 2))


@dataclass(frozen=True, slots=True)
class DecoderParams:
    """Everything the chain needs. Counts-derived fields are filled by `fit`, the rest by the grid.

    temper:             alpha, scale on summed log-evidence. Grid {0.01, 0.02, 0.05, 0.1, 0.2}.  (grid)
    poss_mean_s:        mean H/A spell in seconds; geometric, hazard 1 / (poss_mean_s * FPS / stride). (grid)
    dead_mean_s:        mean D stretch in seconds.                                              (grid)
    p_dead_after_poss:  P(next segment is D | a possession ends).                               (fit)
    p_flip_after_dead:  P(next possession is the OTHER team | a D stretch ends).                (fit)
    stride:             frames per decode block. Speed knob: 5 by default, 1 allowed (0.17 s per half).
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
        p, kickoff = self.params, half.id.kickoff
        ev = self.emission.loglik(half)[kickoff:].astype(np.float64)
        m = ev.shape[0]
        E = p.temper * np.add.reduceat(ev, np.arange(0, m, p.stride), axis=0)
        if p.decode_rule == "marginal":
            post_blocks = _forward_backward(E, _chain(p))
        else:
            post_blocks = np.eye(3)[_map(E, p)]
        post = np.empty((half.n, 3), dtype=np.float64)
        post[:kickoff] = (0.0, 0.0, 1.0)
        post[kickoff:] = np.repeat(post_blocks, p.stride, axis=0)[:m]
        codes = np.round(post, 9).argmax(axis=1).astype(np.int8)
        return Decoded(codes=codes, posterior=post.astype(np.float32))

    def save(self, path: str | Path, provenance: Mapping[str, object]) -> Path:
        """{"emission": {"kind": "tier0", ...}, "params": {...}, "provenance": {...}} with sorted keys
        and fixed float formatting, so the committed file and the submission it produces are both
        byte-stable. Numbers only: no data, no tracking, safe to commit (params/*.json)."""
        doc = {"emission": {"kind": "tier0", **dataclasses.asdict(self.emission)},
               "params": dataclasses.asdict(self.params),
               "provenance": dict(provenance)}
        path = Path(path)
        path.write_bytes((json.dumps(doc, sort_keys=True, indent=2) + "\n").encode("ascii"))
        return path

    @staticmethod
    def load(path: str | Path) -> "Decoder":
        """Boundary: parse + validate ranges (0 < q < 1, 0 < p < 1, temper > 0, stride >= 1).

        Every emission and params field must be present: a default filled in silently would let a
        later change of default alter the submission a committed params file produces. "marginal"
        requires min_*_frames == 1; "map" requires each mean, in blocks, above its minimum in blocks."""
        doc = json.loads(Path(path).read_text())
        if not isinstance(doc, dict) or set(doc) != {"emission", "params", "provenance"}:
            raise ValueError(f"{path}: expected keys emission, params, provenance")
        emission = dict(doc["emission"])
        if emission.pop("kind", None) != "tier0":
            raise ValueError(f"{path}: emission.kind must be 'tier0'")
        decoder = Decoder(_strict(Tier0Emission, emission, path), _strict(DecoderParams, doc["params"], path))
        _validate(decoder, path)
        return decoder


def _strict(cls: type, values: Mapping[str, object], path: str | Path):
    names = {f.name for f in dataclasses.fields(cls)}
    if set(values) != names:
        raise ValueError(f"{path}: {cls.__name__} keys differ: missing {sorted(names - set(values))}, "
                         f"unknown {sorted(set(values) - names)}")
    return cls(**values)


def _validate(decoder: Decoder, path: str | Path) -> None:
    e, p = decoder.emission, decoder.params

    def number(name: str, value: object, lo: float, hi: float, *, integer: bool = False,
               lo_open: bool = True, hi_open: bool = True) -> None:
        kinds = (int,) if integer else (int, float)
        ok = isinstance(value, kinds) and not isinstance(value, bool) and math.isfinite(value)
        ok = ok and (value > lo if lo_open else value >= lo) and (value < hi if hi_open else value <= hi)
        if not ok:
            raise ValueError(f"{path}: {name} = {value!r} outside its range")

    number("q", e.q, 0, 1)
    number("dead_bias", e.dead_bias, 0, math.inf)
    number("alive_share", e.alive_share, 0, 1, hi_open=False)
    number("temper", p.temper, 0, math.inf)
    number("poss_mean_s", p.poss_mean_s, 0, math.inf)
    number("dead_mean_s", p.dead_mean_s, 0, math.inf)
    number("p_dead_after_poss", p.p_dead_after_poss, 0, 1)
    number("p_flip_after_dead", p.p_flip_after_dead, 0, 1)
    number("stride", p.stride, 1, math.inf, integer=True, lo_open=False)
    number("min_poss_frames", p.min_poss_frames, 1, math.inf, integer=True, lo_open=False)
    number("min_dead_frames", p.min_dead_frames, 1, math.inf, integer=True, lo_open=False)
    if p.decode_rule == "marginal":
        if (p.min_poss_frames, p.min_dead_frames) != (1, 1):
            raise ValueError(f"{path}: decode_rule 'marginal' needs min_poss_frames == min_dead_frames == 1")
    elif p.decode_rule == "map":
        mean, k = _blocks(p)
        for name, s in (("poss", H), ("dead", _DH)):
            if mean[s] <= k[s]:
                raise ValueError(f"{path}: decode_rule 'map' needs {name}_mean_s above min_{name}_frames "
                                 f"in blocks of {p.stride}")
    else:
        raise ValueError(f"{path}: decode_rule {p.decode_rule!r} is not 'marginal' or 'map'")


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
    pairs = list(pairs)
    n_poss = n_poss_to_dead = n_dead = n_flip = 0
    for _, labels in pairs:
        for seq in _segment_labels(labels):
            for a, b in zip(seq, seq[1:]):
                if a != D:
                    n_poss += 1
                    n_poss_to_dead += b == D
            for a, b, c in zip(seq, seq[1:], seq[2:]):
                if b == D and a != D and c != D:
                    n_dead += 1
                    n_flip += a != c
    params = dataclasses.replace(base.params,
                                 p_dead_after_poss=(n_poss_to_dead + 1) / (n_poss + 2),
                                 p_flip_after_dead=(n_flip + 1) / (n_dead + 2))
    return Decoder(Tier0Emission.fit(pairs, base.emission), params)


def _segment_labels(labels: NDArray[np.int8]) -> list[list[int]]:
    """The label of each maximal constant segment, one list per maximal non-X stretch. Only adjacent
    entries of one list are observed transitions; a stretch's first and last segments may be truncated
    by X or the half's edge, which is why nothing is counted across lists."""
    graded = np.concatenate(([0], (labels != X).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(graded))
    out = []
    for lo, hi in zip(edges[::2], edges[1::2]):
        w = labels[lo:hi]
        starts = np.concatenate(([0], np.flatnonzero(w[1:] != w[:-1]) + 1))
        out.append(w[starts].tolist())
    return out


# --- internals: kept private, exercised through Decoder.decode -----------------------------------------

@dataclass(frozen=True, slots=True)
class _Chain:
    """trans float64 [4,4] row-stochastic per block; init float64 [4] (0.5, 0.5, 0, 0)."""
    trans: NDArray[np.float64]
    init: NDArray[np.float64]


def _blocks(p: DecoderParams) -> tuple[list[float], list[int]]:
    """Per state (H, A, D_after_H, D_after_A): mean segment length and minimum segment length, both in
    blocks of `stride` frames (the minimum rounded up)."""
    mean = [p.poss_mean_s * FPS / p.stride] * 2 + [p.dead_mean_s * FPS / p.stride] * 2
    k = [math.ceil(p.min_poss_frames / p.stride)] * 2 + [math.ceil(p.min_dead_frames / p.stride)] * 2
    return mean, k


def _switch_into(p: DecoderParams) -> list[list[tuple[int, float]]]:
    """Per target state c: (predecessor q, P(q -> c | q's segment ends)). Shared by both decode rules.
    The order inside a row is `_map`'s tie order (an earlier predecessor wins a tie)."""
    pd, pf = p.p_dead_after_poss, p.p_flip_after_dead
    return [
        [(A, 1 - pd), (_DH, 1 - pf), (_DA, pf)],
        [(H, 1 - pd), (_DA, 1 - pf), (_DH, pf)],
        [(H, pd)],
        [(A, pd)],
    ]


def _chain(p: DecoderParams) -> _Chain:
    """States 0=H 1=A 2=D_after_H 3=D_after_A. With blocks of `stride` frames:
        hp = 1 / (poss_mean_s * FPS / stride)     hd = 1 / (dead_mean_s * FPS / stride)     (clipped to <= 0.5)
        H -> H 1-hp ;  H -> D_after_H hp*p_dead ;  H -> A hp*(1-p_dead)
        D_after_H -> D_after_H 1-hd ;  -> H hd*(1-p_flip) ;  -> A hd*p_flip
        A and D_after_A mirror those.
    """
    mean, _ = _blocks(p)
    hazard = [min(1.0 / m, 0.5) for m in mean]
    trans = np.diag([1 - h for h in hazard])
    for c, row in enumerate(_switch_into(p)):
        for q, w in row:
            trans[q, c] = hazard[q] * w
    return _Chain(trans=trans, init=np.array([0.5, 0.5, 0.0, 0.0]))


def _forward_backward(E: NDArray[np.float64], chain: _Chain) -> NDArray[np.float64]:
    """Scaled forward-backward on block evidence E [nb, 3] -> label posteriors [nb, 3].

    The per-label evidence is broadcast to states through STATE_LABEL. Scaled in the probability
    domain (K = 4 makes log-domain pointless), with each row's evidence max removed first. The
    recursions run on Python floats with every sum written out in a fixed order: no BLAS, no numpy
    reduction whose order could depend on the CPU, so the same bits come out on every machine.
    """
    nb = E.shape[0]
    ek = np.exp(E - E.max(axis=1, keepdims=True))[:, STATE_LABEL].tolist()
    (t00, t01, t02, t03), (t10, t11, t12, t13), (t20, t21, t22, t23), (t30, t31, t32, t33) = chain.trans.tolist()

    i0, i1, i2, i3 = chain.init.tolist()
    e0, e1, e2, e3 = ek[0]
    x0, x1, x2, x3 = i0 * e0, i1 * e1, i2 * e2, i3 * e3
    s = x0 + x1 + x2 + x3
    a0, a1, a2, a3 = x0 / s, x1 / s, x2 / s, x3 / s
    alpha = [a0, a1, a2, a3]
    for e0, e1, e2, e3 in ek[1:]:
        x0 = (a0 * t00 + a1 * t10 + a2 * t20 + a3 * t30) * e0
        x1 = (a0 * t01 + a1 * t11 + a2 * t21 + a3 * t31) * e1
        x2 = (a0 * t02 + a1 * t12 + a2 * t22 + a3 * t32) * e2
        x3 = (a0 * t03 + a1 * t13 + a2 * t23 + a3 * t33) * e3
        s = x0 + x1 + x2 + x3
        a0, a1, a2, a3 = x0 / s, x1 / s, x2 / s, x3 / s
        alpha += (a0, a1, a2, a3)

    b0 = b1 = b2 = b3 = 1.0
    beta = [b0, b1, b2, b3]                 # built from the last block backwards
    for e0, e1, e2, e3 in ek[:0:-1]:
        w0, w1, w2, w3 = e0 * b0, e1 * b1, e2 * b2, e3 * b3
        x0 = t00 * w0 + t01 * w1 + t02 * w2 + t03 * w3
        x1 = t10 * w0 + t11 * w1 + t12 * w2 + t13 * w3
        x2 = t20 * w0 + t21 * w1 + t22 * w2 + t23 * w3
        x3 = t30 * w0 + t31 * w1 + t32 * w2 + t33 * w3
        s = x0 + x1 + x2 + x3
        b0, b1, b2, b3 = x0 / s, x1 / s, x2 / s, x3 / s
        beta += (b0, b1, b2, b3)

    g = np.array(alpha).reshape(nb, 4) * np.array(beta).reshape(nb, 4)[::-1]
    g /= (g[:, 0] + g[:, 1] + g[:, 2] + g[:, 3])[:, None]
    return np.stack([g[:, 0], g[:, 1], g[:, 2] + g[:, 3]], axis=1)


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
                take new only if new > cont (a tie keeps the running segment: the earlier switch)
                ent[t+1][c] = max over predecessors q of V_t[q] + log(1 - c_q) + log T[q -> c]
        end:    best of V at nb-1 and of the right-censored tails ent[s][c] + C[nb, c] - C[s, c].
        back:   hop segment to segment through the stored segment starts and entry predecessors.

    Model constants (log tables) are rounded to 1e-12 before use so an ulp of libm drift cannot move a
    near-tie boundary. Port of the bakeoff's probe; selfcheck.map_equals_expanded_viterbi pins it.
    The first segment has no minimum (it is already under way at the kickoff); the last may be cut
    short by the end of the half. Ties between states go to the lower state index.
    """
    nb, K = E.shape[0], N_STATES
    ll = E[:, STATE_LABEL]
    C = np.concatenate([np.zeros((1, K)), np.cumsum(ll, axis=0)]).tolist()
    ll = ll.tolist()

    mean, k = _blocks(p)
    cont_p = [(m - kc) / (m - kc + 1) for m, kc in zip(mean, k)]
    log_c = [round(math.log(c), 12) for c in cont_p]
    entry_w = [[(q, round(math.log(1 - cont_p[q]) + math.log(w), 12)) for q, w in row] for row in _switch_into(p)]
    log_pi = [round(math.log(0.5), 12)] * 2 + [-math.inf] * 2

    ent = [[-math.inf] * K for _ in range(nb + 1)]   # ent[s][c]: best score of a fresh c segment at s
    ent_from = [[-1] * K for _ in range(nb + 1)]
    start = [None] * nb                                # start[t][c]: segment start of the best path

    def fill_entry(s: int, V: list[float]) -> None:
        for c in range(K):
            best, arg = -math.inf, -1
            for q, w in entry_w[c]:
                v = V[q] + w
                if v > best:
                    best, arg = v, q
            ent[s][c], ent_from[s][c] = best, arg

    V = [log_pi[c] + ll[0][c] for c in range(K)]
    start[0] = [0] * K
    fill_entry(1, V)
    for t in range(1, nb):
        lt, ct1, prev_start = ll[t], C[t + 1], start[t - 1]
        V_t, row = [0.0] * K, [0] * K
        for c in range(K):
            cont = V[c] + log_c[c] + lt[c]
            s = t - k[c] + 1
            if s >= 1:
                new = ent[s][c] + ct1[c] - C[s][c]
                if new > cont:
                    V_t[c], row[c] = new, s
                    continue
            V_t[c], row[c] = cont, prev_start[c]
        V, start[t] = V_t, row
        if t + 1 < nb:
            fill_entry(t + 1, V)

    best_c = max(range(K), key=lambda c: V[c])
    best_v, tail = V[best_c], None
    for c in range(K):
        for s in range(max(1, nb - k[c] + 1), nb):
            v = ent[s][c] + C[nb][c] - C[s][c]
            if v > best_v:
                best_v, best_c, tail = v, c, s

    labels = np.empty(nb, dtype=np.int8)
    t, c = nb - 1, best_c
    if tail is not None:
        labels[tail:] = STATE_LABEL[c]
        t, c = tail - 1, ent_from[tail][c]
    while True:
        s = start[t][c]
        labels[s:t + 1] = STATE_LABEL[c]
        if s == 0:
            return labels
        t, c = s - 1, ent_from[s][c]
