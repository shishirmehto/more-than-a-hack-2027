from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Literal, Mapping, NamedTuple, TypeVar

import numpy as np
from numpy.typing import NDArray

from .half import A, AWAY, D, FPS, H, HOME, NO_TEAM, Half


class State(IntEnum):
    """The chain's states; each value is the state's row and column in the chain's matrices. The two
    D states both emit label D and remember who had the ball before the stoppage."""
    H = 0
    A = 1
    D_AFTER_H = 2
    D_AFTER_A = 3


N_STATES = len(State)
STATE_LABEL = np.array([{State.H: H, State.A: A, State.D_AFTER_H: D, State.D_AFTER_A: D}[s] for s in State],
                       dtype=np.int8)

_M_FLOOR, _M_CAP = 1e-6, 0.98


@dataclass(frozen=True, slots=True)
class Tier0Emission:
    """Evidence from `Half.nearest_team`: token in {HOME, AWAY, none}, optionally sharpened by the
    Half's BallGeometry.

    Model, per frame with label k in {H, A, D}:
        P(none | k)         = m_k
        P(token t | k)      = (1 - m_k) * T[k, t]
    T is team-symmetric: T[H, HOME] = T[A, AWAY] = q, T[H, AWAY] = T[A, HOME] = 1 - q, T[D, .] = (.5, .5).
    m_H = m_A = m_alive, m_D = dead_bias * m_alive, with m_alive solved per half from the half's
    OBSERVED missing rate r over [kickoff, n) and a prior alive share a0:
        r = m_alive * (a0 + (1 - a0) * dead_bias)        (clipped to 0.98)
    dead_bias = 1.0 makes every missing frame's row flat.

    q:           P(token == label's team | alive, ball seen).
    alive_share: a0, prior over the alive share of the half.

    Geometry terms, each off at its default (and then left out of a saved file). Any of them on makes
    the emission need Half.geometry (`needs_geometry`), which only challenge.observe supplies:
    margin_scale_m: lambda > 0 replaces the constant q on seen frames by
                    q(m) = 0.5 + (q_max - 0.5) * (1 - exp(-m / lambda)), m = BallGeometry.margin_m.
                    0 keeps the constant q.
    q_max:          the asymptote of q(m); ignored when margin_scale_m is 0.
    outside_bonus:  log-evidence added to D on frames whose ball lies more than outside_min_m metres
                    outside the pitch.
    far_bonus:      log-evidence added to D on frames whose nearest player is more than far_min_m metres
                    from the ball.
    Checked at construction: 0 < q < 1, dead_bias > 0, 0 < alive_share <= 1, margin_scale_m >= 0,
    0.5 < q_max < 1, finite bonuses, outside_min_m >= 0, far_min_m > 0.
    """
    q: float = 0.78
    dead_bias: float = 1.0
    alive_share: float = 0.6
    margin_scale_m: float = 0.0
    q_max: float = 0.95
    outside_bonus: float = 0.0
    outside_min_m: float = 1.0
    far_bonus: float = 0.0
    far_min_m: float = 10.0

    def __post_init__(self) -> None:
        _number("q", self.q, 0, 1)
        _number("dead_bias", self.dead_bias, 0, math.inf)
        _number("alive_share", self.alive_share, 0, 1, hi_open=False)
        _number("margin_scale_m", self.margin_scale_m, 0, math.inf, lo_open=False)
        _number("q_max", self.q_max, 0.5, 1)
        _number("outside_bonus", self.outside_bonus, -math.inf, math.inf)
        _number("outside_min_m", self.outside_min_m, 0, math.inf, lo_open=False)
        _number("far_bonus", self.far_bonus, -math.inf, math.inf)
        _number("far_min_m", self.far_min_m, 0, math.inf)

    @property
    def needs_geometry(self) -> bool:
        return self.margin_scale_m > 0 or self.outside_bonus != 0 or self.far_bonus != 0

    def loglik(self, half: Half) -> NDArray[np.float32]:
        tok = half.nearest_team
        r = float((tok[half.id.kickoff:] == NO_TEAM).mean())
        rho, a0, q = self.dead_bias, self.alive_share, self.q
        m_a = min(max(r / (a0 + (1 - a0) * rho), _M_FLOOR), _M_CAP)
        m_d = min(max(rho * m_a, _M_FLOOR), _M_CAP)
        seen = np.log([1 - m_a, 1 - m_a, 1 - m_d])
        row_by_token = {
            NO_TEAM: np.log([m_a, m_a, m_d]),
            HOME: np.log([q, 1 - q, 0.5]) + seen,
            AWAY: np.log([1 - q, q, 0.5]) + seen,
        }
        out = np.empty((half.n, 3), dtype=np.float64)
        for token, row in row_by_token.items():
            out[tok == token] = row
        if self.needs_geometry:
            self._add_geometry(out, half, seen)
        return out.astype(np.float32)

    def _add_geometry(self, out: NDArray[np.float64], half: Half, seen: NDArray[np.float64]) -> None:
        g = half.geometry
        if g is None:
            raise ValueError(f"{half.id}: this emission reads ball geometry (margin_scale_m, outside_bonus or "
                             "far_bonus) and the Half has none; observe it from a Geometry "
                             "(challenge.halves('atd')), not from baseline_raw")
        if self.margin_scale_m > 0:
            where = half.nearest_team != NO_TEAM
            margin = g.margin_m[where].astype(np.float64)
            qm = 0.5 + (self.q_max - 0.5) * -np.expm1(-margin / self.margin_scale_m)
            home = half.nearest_team[where] == HOME
            hit, miss = np.log(qm), np.log1p(-qm)
            out[where, 0] = np.where(home, hit, miss) + seen[0]
            out[where, 1] = np.where(home, miss, hit) + seen[1]
        if self.outside_bonus:
            out[g.outside_m > self.outside_min_m, 2] += self.outside_bonus
        if self.far_bonus:
            out[g.nearest_m > self.far_min_m, 2] += self.far_bonus


@dataclass(frozen=True, slots=True)
class DecoderParams:
    """
    temper:             alpha, scale on summed log-evidence.
    poss_mean_s:        mean H/A spell in seconds; geometric, hazard 1 / (poss_mean_s * FPS / stride).
    dead_mean_s:        mean D stretch in seconds.
    p_dead_after_poss:  P(next segment is D | a possession ends).
    p_flip_after_dead:  P(next possession is the OTHER team | a D stretch ends).
    stride:             frames per decode block.
    decode_rule:        "marginal" | "map".
    min_poss_frames:    hard minimum H/A segment length in frames; "map" only, 1 = none.
    min_dead_frames:    hard minimum D segment length in frames; "map" only, 1 = none.
    dead_min_run:       0 keeps the chain's own D. Otherwise D is exactly the ball-missing runs of at
                        least this many frames, each shrunk by dead_trim frames at both ends, and every
                        other frame takes the chain's team (its D filled from the previous team call).
                        A run touching a half's first or last frame counts as unbounded on that side.
                        101 with dead_trim 50 gives starter/baseline.py's smooth50 D mask ("no ball
                        within 50 frames"); the team labels still come from the chain.
    dead_trim:          frames cut from each end of a dead run; ignored when dead_min_run is 0.
    dead_close:         a stretch of team calls shorter than this many frames with dead runs on both
                        sides becomes D too, so brief ball sightings inside one stoppage do not split it
                        into spurious possessions; 0 = off, ignored when dead_min_run is 0.
    dead_outside_m:     0 is off. Otherwise a frame whose ball is seen more than this many metres outside
                        the pitch (Half.geometry.outside_m) counts as missing when the dead_min_run rule
                        finds its runs; needs Half.geometry. Ignored when dead_min_run is 0.

    Under "map" a segment of state s lasts min + Geometric frames with mean poss_mean_s / dead_mean_s
    (shifted geometric), so mean > min is required. Minimums are converted to blocks by ceil(min / stride).
    They bind interior segments only: a half's first and last segments can be shorter.
    Checked at construction: temper and both means > 0, both probabilities in (0, 1), stride and both
    minimums integers >= 1; "marginal" requires both minimums 1; "map" requires each mean, in blocks,
    above its minimum in blocks.

    H/A symmetric by construction: no home-advantage prior, and no swap of tokens can change the answer.
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
    dead_min_run: int = 0
    dead_trim: int = 0
    dead_close: int = 0
    dead_outside_m: float = 0.0

    def __post_init__(self) -> None:
        _number("temper", self.temper, 0, math.inf)
        _number("poss_mean_s", self.poss_mean_s, 0, math.inf)
        _number("dead_mean_s", self.dead_mean_s, 0, math.inf)
        _number("p_dead_after_poss", self.p_dead_after_poss, 0, 1)
        _number("p_flip_after_dead", self.p_flip_after_dead, 0, 1)
        _number("stride", self.stride, 1, math.inf, integer=True, lo_open=False)
        _number("min_poss_frames", self.min_poss_frames, 1, math.inf, integer=True, lo_open=False)
        _number("min_dead_frames", self.min_dead_frames, 1, math.inf, integer=True, lo_open=False)
        _number("dead_min_run", self.dead_min_run, 0, math.inf, integer=True, lo_open=False)
        _number("dead_trim", self.dead_trim, 0, math.inf, integer=True, lo_open=False)
        _number("dead_close", self.dead_close, 0, math.inf, integer=True, lo_open=False)
        _number("dead_outside_m", self.dead_outside_m, 0, math.inf, lo_open=False)
        if self.dead_min_run and 2 * self.dead_trim >= self.dead_min_run:
            raise ValueError("dead_trim must leave part of a dead_min_run run: 2 * dead_trim < dead_min_run")
        if not self.dead_min_run and (self.dead_trim or self.dead_close or self.dead_outside_m):
            raise ValueError("dead_trim, dead_close and dead_outside_m act only with dead_min_run > 0")
        if self.decode_rule == "marginal":
            if (self.min_poss_frames, self.min_dead_frames) != (1, 1):
                raise ValueError("decode_rule 'marginal' needs min_poss_frames == min_dead_frames == 1")
        elif self.decode_rule == "map":
            mean, k = _blocks(self)
            for name, s in (("poss", State.H), ("dead", State.D_AFTER_H)):
                if mean[s] <= k[s]:
                    raise ValueError(f"decode_rule 'map' needs {name}_mean_s above min_{name}_frames "
                                     f"in blocks of {self.stride}")
        else:
            raise ValueError(f"decode_rule {self.decode_rule!r} is not 'marginal' or 'map'")


_EMISSION_FIELDS = frozenset(f.name for f in dataclasses.fields(Tier0Emission))
_OPTIONAL_EMISSION = {f.name: f.default for f in dataclasses.fields(Tier0Emission)
                      if f.name in ("margin_scale_m", "q_max", "outside_bonus", "outside_min_m", "far_bonus",
                                    "far_min_m")}
_OPTIONAL_PARAMS = {"dead_min_run": 0, "dead_trim": 0, "dead_close": 0, "dead_outside_m": 0.0}
if _EMISSION_FIELDS & {f.name for f in dataclasses.fields(DecoderParams)}:
    raise ImportError("Tier0Emission and DecoderParams share a field name, so Decoder.replace cannot route it")


@dataclass(frozen=True, slots=True)
class Decoded:
    """codes:     int8 [n] in {0,1,2}, never X. A Decoder labels frames [0, kickoff) D.
    posterior: float32 [n, 3] P(H, A, D | all evidence) under "marginal", (0, 0, 1) before kickoff.
               None under "map", which finds one best path and has no posterior.
    """
    codes: NDArray[np.int8]
    posterior: NDArray[np.float32] | None


@dataclass(frozen=True, slots=True)
class Decoder:
    """An immutable, JSON-serialisable decoder. `decode` is a pure function of (self, half)."""
    emission: Tier0Emission
    params: DecoderParams

    def decode(self, half: Half) -> Decoded:
        """Label one half. Deterministic: float64 throughout, no RNG, no BLAS in the loop.

        Contract, in the order it is applied:
          1. frames [0, half.id.kickoff) are D by rule (the challenge grades half 2's first 2934 frames
             as D; an X head would be back-filled with the first label and become a false 117 s spell).
          2. decode [kickoff, n) from a uniform start over {H, A}.
          3. "map": codes are the labels of the MAP path. "marginal": codes = argmax over
             round(posterior, 9). The rounding makes exact symmetric ties (a flat block at the start of
             a half) resolve to the lower label on every machine instead of on 1-ulp noise.
          4. dead_min_run > 0 replaces the chain's D by the missing-run rule (see DecoderParams), and
             the posterior is dropped because it no longer describes the codes.
        """
        p, kickoff = self.params, half.id.kickoff
        ev = self.emission.loglik(half)[kickoff:].astype(np.float64)
        m = ev.shape[0]
        E = p.temper * np.add.reduceat(ev, np.arange(0, m, p.stride), axis=0)
        if p.decode_rule == "map":
            codes = np.full(half.n, D, dtype=np.int8)
            codes[kickoff:] = np.repeat(_map(E, p), p.stride)[:m]
            return Decoded(codes=_missing_run_dead(codes, half, p), posterior=None)
        post = np.empty((half.n, 3), dtype=np.float64)
        post[:kickoff] = (0.0, 0.0, 1.0)
        post[kickoff:] = np.repeat(_forward_backward(E, _chain(p)), p.stride, axis=0)[:m]
        codes = np.round(post, 9).argmax(axis=1).astype(np.int8)
        if p.dead_min_run:
            return Decoded(codes=_missing_run_dead(codes, half, p), posterior=None)
        return Decoded(codes=codes, posterior=post.astype(np.float32))

    @property
    def needs_geometry(self) -> bool:
        """True when decoding reads Half.geometry, which only challenge.observe supplies."""
        return self.emission.needs_geometry or bool(self.params.dead_min_run and self.params.dead_outside_m)

    def replace(self, **flat: object) -> "Decoder":
        """A copy with fields changed by flat name. Each key goes to the emission or the params,
        whichever declares it; an unknown name raises TypeError."""
        emission = {k: v for k, v in flat.items() if k in _EMISSION_FIELDS}
        params = {k: v for k, v in flat.items() if k not in _EMISSION_FIELDS}
        return Decoder(dataclasses.replace(self.emission, **emission), dataclasses.replace(self.params, **params))

    def fields(self) -> dict[str, object]:
        """Every emission and params field by flat name, emission first: the names `replace` takes."""
        return {**dataclasses.asdict(self.emission), **dataclasses.asdict(self.params)}

    def save(self, path: str | Path, provenance: Mapping[str, object]) -> Path:
        """{"emission": {"kind": "tier0", ...}, "params": {...}, "provenance": {...}} with sorted keys
        and fixed float formatting, so the committed file and the submission it produces are both
        byte-stable. An optional param at its off value is left out, so files written before it
        existed round-trip unchanged. The same holds for the emission's geometry terms."""
        doc = {"emission": {"kind": "tier0", **_without_off(self.emission)},
               "params": _without_off(self.params),
               "provenance": dict(provenance)}
        path = Path(path)
        path.write_bytes((json.dumps(doc, sort_keys=True, indent=2) + "\n").encode("ascii"))
        return path

    @staticmethod
    def load(path: str | Path) -> "Decoder":
        """Every emission and params field must be present. Every ValueError names the file."""
        doc = json.loads(Path(path).read_text())
        if not isinstance(doc, dict) or set(doc) != {"emission", "params", "provenance"}:
            raise ValueError(f"{path}: expected keys emission, params, provenance")
        emission = dict(doc["emission"])
        if emission.pop("kind", None) != "tier0":
            raise ValueError(f"{path}: emission.kind must be 'tier0'")
        try:
            return Decoder(_strict(Tier0Emission, emission), _strict(DecoderParams, doc["params"]))
        except ValueError as error:
            raise ValueError(f"{path}: {error}") from None


def _optional(cls: type) -> Mapping[str, object]:
    return {Tier0Emission: _OPTIONAL_EMISSION, DecoderParams: _OPTIONAL_PARAMS}[cls]


def _without_off(obj: Tier0Emission | DecoderParams) -> dict[str, object]:
    off = _optional(type(obj))
    return {k: v for k, v in dataclasses.asdict(obj).items() if k not in off or v != off[k]}


def _strict(cls: type, values: Mapping[str, object]):
    names = {f.name for f in dataclasses.fields(cls)}
    values = {**_optional(cls), **values}
    if set(values) != names:
        raise ValueError(f"{cls.__name__} keys differ: missing {sorted(names - set(values))}, "
                         f"unknown {sorted(set(values) - names)}")
    return cls(**values)


def _missing_run_dead(codes: NDArray[np.int8], half: Half, p: DecoderParams) -> NDArray[np.int8]:
    if not p.dead_min_run:
        return codes
    kickoff, n = half.id.kickoff, half.n
    team = codes.copy()
    called = np.flatnonzero(team != D)
    if len(called):
        last = np.maximum.accumulate(np.where(team != D, np.arange(n), -1))
        team = np.where(last >= 0, team[np.maximum(last, 0)], team[called[0]]).astype(np.int8)
    unseen = half.nearest_team == NO_TEAM
    if p.dead_outside_m:
        if half.geometry is None:
            raise ValueError(f"{half.id}: dead_outside_m reads ball geometry and the Half has none; observe it "
                             "from a Geometry (challenge.halves('atd')), not from baseline_raw")
        unseen = unseen | (half.geometry.outside_m > p.dead_outside_m)
    missing = np.concatenate(([False], unseen, [False]))
    edges = np.flatnonzero(np.diff(missing.view(np.int8)))
    dead = np.zeros(n + 1, dtype=np.int32)
    for start, stop in zip(edges[::2], edges[1::2]):
        lo = start + p.dead_trim if start > 0 else -p.dead_min_run
        hi = stop - p.dead_trim if stop < n else n + p.dead_min_run
        if hi - lo >= p.dead_min_run - 2 * p.dead_trim and min(hi, n) > max(lo, 0):
            dead[max(lo, 0)] += 1
            dead[min(hi, n)] -= 1
    out = np.where(np.cumsum(dead[:n]) > 0, D, team).astype(np.int8)
    out[:kickoff] = D
    if p.dead_close:
        live = np.concatenate(([False], out != D, [False]))
        edges = np.flatnonzero(np.diff(live.view(np.int8)))
        for start, stop in zip(edges[::2], edges[1::2]):
            if start > kickoff and stop < n and stop - start < p.dead_close:
                out[start:stop] = D
    return out


def _number(name: str, value: object, lo: float, hi: float, *, integer: bool = False,
            lo_open: bool = True, hi_open: bool = True) -> None:
    kinds = (int,) if integer else (int, float)
    ok = isinstance(value, kinds) and not isinstance(value, bool) and math.isfinite(value)
    ok = ok and (value > lo if lo_open else value >= lo) and (value < hi if hi_open else value <= hi)
    if not ok:
        raise ValueError(f"{name} = {value!r} outside its range")


@dataclass(frozen=True, slots=True)
class _Chain:
    trans: NDArray[np.float64]
    init: NDArray[np.float64]


_T = TypeVar("_T")


def _by_state(poss: _T, dead: _T) -> list[_T]:
    """One value per State, in State order: `poss` for H and A, `dead` for both D states."""
    return [dead if STATE_LABEL[s] == D else poss for s in State]


def _blocks(p: DecoderParams) -> tuple[list[float], list[int]]:
    mean = _by_state(p.poss_mean_s * FPS / p.stride, p.dead_mean_s * FPS / p.stride)
    k = _by_state(math.ceil(p.min_poss_frames / p.stride), math.ceil(p.min_dead_frames / p.stride))
    return mean, k


class _Switch(NamedTuple):
    source: State
    weight: float


def _switch_into(p: DecoderParams) -> dict[State, tuple[_Switch, ...]]:
    """For each state, the states whose segment can end by switching into it, each with
    P(the next segment is this state | the source segment ends). The order of a row is _map's
    tie-break: on an exact tie the earlier source wins."""
    pd, pf = p.p_dead_after_poss, p.p_flip_after_dead
    return {
        State.H: (_Switch(State.A, 1 - pd), _Switch(State.D_AFTER_H, 1 - pf), _Switch(State.D_AFTER_A, pf)),
        State.A: (_Switch(State.H, 1 - pd), _Switch(State.D_AFTER_A, 1 - pf), _Switch(State.D_AFTER_H, pf)),
        State.D_AFTER_H: (_Switch(State.H, pd),),
        State.D_AFTER_A: (_Switch(State.A, pd),),
    }


def _chain(p: DecoderParams) -> _Chain:
    mean, _ = _blocks(p)
    hazard = [min(1.0 / m, 0.5) for m in mean]
    trans = np.diag([1 - h for h in hazard])
    for target, row in _switch_into(p).items():
        for source, weight in row:
            trans[source, target] = hazard[source] * weight
    return _Chain(trans=trans, init=np.array(_by_state(0.5, 0.0)))


def _forward_backward(E: NDArray[np.float64], chain: _Chain) -> NDArray[np.float64]:
    """The recursions run on Python floats with every sum written out in a fixed order: no BLAS, no
    numpy reduction whose order could depend on the CPU, so the same bits come out on every machine.
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
    beta_last_block_first = [b0, b1, b2, b3]
    for e0, e1, e2, e3 in ek[:0:-1]:
        w0, w1, w2, w3 = e0 * b0, e1 * b1, e2 * b2, e3 * b3
        x0 = t00 * w0 + t01 * w1 + t02 * w2 + t03 * w3
        x1 = t10 * w0 + t11 * w1 + t12 * w2 + t13 * w3
        x2 = t20 * w0 + t21 * w1 + t22 * w2 + t23 * w3
        x3 = t30 * w0 + t31 * w1 + t32 * w2 + t33 * w3
        s = x0 + x1 + x2 + x3
        b0, b1, b2, b3 = x0 / s, x1 / s, x2 / s, x3 / s
        beta_last_block_first += (b0, b1, b2, b3)

    g = np.array(alpha).reshape(nb, 4) * np.array(beta_last_block_first).reshape(nb, 4)[::-1]
    g /= (g[:, 0] + g[:, 1] + g[:, 2] + g[:, 3])[:, None]
    return np.stack([g[:, State.H], g[:, State.A], g[:, State.D_AFTER_H] + g[:, State.D_AFTER_A]], axis=1)


def _map(E: NDArray[np.float64], p: DecoderParams) -> NDArray[np.int8]:
    """Model constants (log tables) are rounded to 1e-12 before use so an ulp of libm drift cannot
    move a near-tie boundary.
    """
    nb, K = E.shape[0], N_STATES
    ll = E[:, STATE_LABEL]
    C = np.concatenate([np.zeros((1, K)), np.cumsum(ll, axis=0)]).tolist()
    ll = ll.tolist()

    mean, k = _blocks(p)
    cont_p = [(m - kc) / (m - kc + 1) for m, kc in zip(mean, k)]
    log_c = [round(math.log(c), 12) for c in cont_p]
    switch_into = _switch_into(p)
    entry_w = [[(source, round(math.log(1 - cont_p[source]) + math.log(weight), 12))
                for source, weight in switch_into[c]] for c in State]
    log_pi = _by_state(round(math.log(0.5), 12), -math.inf)

    entry_score = [[-math.inf] * K for _ in range(nb + 1)]
    entry_source = [[-1] * K for _ in range(nb + 1)]
    segment_start = [None] * nb

    def fill_entry(s: int, V: list[float]) -> None:
        for c in range(K):
            best, arg = -math.inf, -1
            for q, w in entry_w[c]:
                v = V[q] + w
                if v > best:
                    best, arg = v, q
            entry_score[s][c], entry_source[s][c] = best, arg

    V = [log_pi[c] + ll[0][c] for c in range(K)]
    segment_start[0] = [0] * K
    fill_entry(1, V)
    for t in range(1, nb):
        lt, ct1, prev_start = ll[t], C[t + 1], segment_start[t - 1]
        V_t, start_t = [0.0] * K, [0] * K
        for c in range(K):
            cont = V[c] + log_c[c] + lt[c]
            s = t - k[c] + 1
            if s >= 1:
                new = entry_score[s][c] + ct1[c] - C[s][c]
                if new > cont:
                    V_t[c], start_t[c] = new, s
                    continue
            V_t[c], start_t[c] = cont, prev_start[c]
        V, segment_start[t] = V_t, start_t
        if t + 1 < nb:
            fill_entry(t + 1, V)

    best_c = max(range(K), key=lambda c: V[c])
    best_v, tail = V[best_c], None
    for c in range(K):
        for s in range(max(1, nb - k[c] + 1), nb):
            v = entry_score[s][c] + C[nb][c] - C[s][c]
            if v > best_v:
                best_v, best_c, tail = v, c, s

    labels = np.empty(nb, dtype=np.int8)
    t, c = nb - 1, best_c
    if tail is not None:
        labels[tail:] = STATE_LABEL[c]
        t, c = tail - 1, entry_source[tail][c]
    while True:
        s = segment_start[t][c]
        labels[s:t + 1] = STATE_LABEL[c]
        if s == 0:
            return labels
        t, c = s - 1, entry_source[s][c]
