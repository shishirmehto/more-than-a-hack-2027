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
_MARGIN_CAP_M = 30.0
_SPEED_CAP_MPS = 40.0
_DEAD_RULE_FIELDS = ("dead_trim", "dead_close", "dead_outside_m", "dead_still_mps", "dead_pace_still_mps",
                     "dead_pace_live_mps", "dead_lead_cut", "dead_out_lead_cut", "dead_out_min_run",
                     "dead_end_cut")
_OUT_BEFORE, _OUT_AFTER = 25, 75
_END_WINDOW = 250
_LOGIT_FIELDS = ("q_logit_a", "q_logit_dist", "q_logit_margin", "q_logit_speed", "q_logit_dist_speed", "q_logit_rel",
                 "q_logit_goal")
SPELL_FEATURES = ("len", "seen", "own_tok", "other_tok", "closest_own", "speed_med", "speed_max", "margin_own",
                  "push", "logodds", "sandwiched", "prev_len", "next_len", "next_to_d", "touch_own", "touch_other",
                  "rel_own", "shape_own", "held_own", "goal_own", "goal_other", "kick_own", "kick_other")
_SHAPE_LAG = 50
_HELD_RADIUS_M = 1.0
_TOUCH_STEP, _TOUCH_RADIUS_M, _TOUCH_SLACK = 5, 1.5, 25


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

    Geometry term, off at its default (and then left out of a saved file). On, it makes the emission
    need Half.geometry (`needs_geometry`), which only challenge.observe supplies:
    q_logit_a, q_logit_dist, q_logit_margin, q_logit_speed, q_logit_dist_speed: (a, b, c, e, f). Any
                    non-zero replaces the constant q on seen frames by q = 1 / (1 + exp(-z)) with
                    z = a + b ln(1 + d) + c ln(1 + min(m, 30)) + e ln(1 + v) + f ln(1 + d) ln(1 + v),
                    d = BallGeometry.nearest_m, m = BallGeometry.margin_m (inf when a team has no slot)
                    and v = min(BallGeometry.speed_mps, 40). A fitted q can fall below 0.5, where a token
                    points away from its own team.
    q_logit_rel:    adds g ln(1 + min(r, 40)) to z, r = BallGeometry.rel_mps, the ball's speed relative to the
                    nearest player: a ball moving with its player makes the token more reliable.
    q_logit_goal:   adds h sign(u) ln(1 + min(|u|, 40)) to z, u = BallGeometry.goal_mps, the ball's x velocity
                    toward the goal the token's team defends: when the ball travels fast at the token team's
                    own goal the token is less often right, so a negative h lowers q there.
    Checked at construction: 0 < q < 1, dead_bias > 0, 0 < alive_share <= 1, finite q_logit terms.
    """
    q: float = 0.78
    dead_bias: float = 1.0
    alive_share: float = 0.6
    q_logit_a: float = 0.0
    q_logit_dist: float = 0.0
    q_logit_margin: float = 0.0
    q_logit_speed: float = 0.0
    q_logit_dist_speed: float = 0.0
    q_logit_rel: float = 0.0
    q_logit_goal: float = 0.0

    def __post_init__(self) -> None:
        _number("q", self.q, 0, 1)
        _number("dead_bias", self.dead_bias, 0, math.inf)
        _number("alive_share", self.alive_share, 0, 1, hi_open=False)
        for name in _LOGIT_FIELDS:
            _number(name, getattr(self, name), -math.inf, math.inf)

    @property
    def needs_geometry(self) -> bool:
        return any(getattr(self, name) for name in _LOGIT_FIELDS)

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
            raise ValueError(f"{half.id}: this emission reads ball geometry (q_logit) and the Half has none; "
                             "observe it from a Geometry (challenge.halves('atd')), not from baseline_raw")
        where = half.nearest_team != NO_TEAM
        nearest = g.nearest_m[where].astype(np.float64)
        margin = np.minimum(g.margin_m[where].astype(np.float64), _MARGIN_CAP_M)
        speed = np.log1p(np.minimum(g.speed_mps[where].astype(np.float64), _SPEED_CAP_MPS))
        z = (self.q_logit_a + self.q_logit_dist * np.log1p(nearest) + self.q_logit_margin * np.log1p(margin)
             + (self.q_logit_speed + self.q_logit_dist_speed * np.log1p(nearest)) * speed)
        if self.q_logit_rel:
            if g.rel_mps is None:
                raise ValueError(f"{half.id}: q_logit_rel reads BallGeometry.rel_mps and this Half has none")
            z = z + self.q_logit_rel * np.log1p(np.minimum(g.rel_mps[where].astype(np.float64), _SPEED_CAP_MPS))
        if self.q_logit_goal:
            if g.goal_mps is None:
                raise ValueError(f"{half.id}: q_logit_goal reads BallGeometry.goal_mps and this Half has none")
            u = np.clip(g.goal_mps[where].astype(np.float64), -_SPEED_CAP_MPS, _SPEED_CAP_MPS)
            z = z + self.q_logit_goal * np.sign(u) * np.log1p(np.abs(u))
        hit, miss = -np.logaddexp(0.0, -z), -np.logaddexp(0.0, z)
        home = half.nearest_team[where] == HOME
        out[where, 0] = np.where(home, hit, miss) + seen[0]
        out[where, 1] = np.where(home, miss, hit) + seen[1]


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
    dead_lead_cut:      0 is off. Otherwise a dead run that does not touch the half's first frame loses only
                        dead_trim minus this many frames at its start (at least 0); its end keeps dead_trim.
                        Whether a run counts still depends only on its length. Needs dead_min_run.
    dead_end_cut:       0 is off. Otherwise a dead run that does not touch the half's last frame loses only
                        dead_trim minus this many frames at its end, so its D ends that much later. Whether a
                        run counts still depends only on its length. Needs dead_min_run.
    dead_out_lead_cut:  0 is off. Otherwise a further cut of the start trim, for a dead run whose ball is
                        seen more than dead_outside_m outside the pitch from 25 frames before to 75 frames
                        after the run's start: a ball seen leaving the pitch dates the stoppage. Needs
                        dead_outside_m.
    dead_out_min_run:   0 is off. Otherwise a run with that same ball-out evidence counts as dead from this
                        many frames instead of dead_min_run. Needs dead_outside_m.
    dead_line_m, dead_line_min_run: 0 is off; set both or neither. A run without ball-out evidence whose
                        ball is seen within dead_line_m metres of a touchline or goal line (BallGeometry.line_m,
                        outside counts) in the 25 frames before its start counts as dead from dead_line_min_run
                        frames instead of dead_min_run: a ball lost next to a line is often out of play.
    dead_return_m, dead_return_min_run: 0 is off; set both or neither. A run whose ball reappears at least
                        dead_return_m metres from where it vanished (the largest Half.return_m inside the run)
                        counts as dead only from dead_return_min_run frames: a ball that travelled far while
                        unseen was mostly in play. Needs dead_min_run.
    dead_end_lead, dead_end_live_mps: 0 is off; set both or neither. A dead run's end moves back to the first
                        frame t of its last 250 frames whose median player speed dead_end_lead frames later
                        (Half.pace_mps at t + dead_end_lead) is above dead_end_live_mps: players speed up 1 to 4 s
                        after a restart, so that frame is already live. Needs dead_min_run.
    dead_line_lead_cut: 0 is off. Otherwise that near-line run's start trim is cut by this many frames more,
                        as dead_out_lead_cut does for ball-out runs. Needs dead_line_m.
    dead_close:         a stretch of team calls shorter than this many frames with dead runs on both
                        sides becomes D too, so brief ball sightings inside one stoppage do not split it
                        into spurious possessions; 0 = off, ignored when dead_min_run is 0.
    dead_outside_m:     0 is off. Otherwise a frame whose ball is seen more than this many metres outside
                        the pitch (Half.geometry.outside_m) counts as missing when the dead_min_run rule
                        finds its runs; needs Half.geometry. Ignored when dead_min_run is 0.
    dead_still_mps:     0 is off. Otherwise a frame whose ball is seen moving slower than this many m/s
                        (Half.geometry.speed_mps), inside a run of at least dead_still_frames such frames,
                        counts as missing when the dead_min_run rule finds its runs: a ball at rest for
                        seconds is usually being placed for a restart. Needs Half.geometry and dead_min_run.
    dead_still_frames:  the shortest run of slow frames that dead_still_mps counts; set exactly when
                        dead_still_mps is.
    dead_pace_still_mps: 0 is off. Otherwise a frame whose median player speed (Half.pace_mps) is below this
                        counts as missing when the dead_min_run rule finds its runs: players walk during
                        stoppages. Needs dead_min_run.
    dead_pace_live_mps: 0 is off. Otherwise a frame whose median player speed is above this never counts as
                        missing, whatever the other dead_* rules say: the tracker lost the ball but play goes
                        on. Needs dead_min_run.
    handover_lag:       inside each run of team calls, every hand-over between the teams moves this many
                        frames later; the run's edges stay put. 0 is off. The nearest-team token flips
                        while a pass is in the air, before the receiver's touch that labels mark.
    spell_merge_frames: 0 is off. Otherwise, after the dead-run rule and before the lag, a possession
                        shorter than this whose two neighbours are possessions joins them, shortest first;
                        one that directly follows a dead stretch is kept. A short possession the chain
                        calls inside another team's is more often wrong than right.
    spell_merge_tails:  1 also lets a short possession before a dead stretch or the half's end join the
                        possession before it, as metrica.rule.merge_short does to labels. Needs
                        spell_merge_frames.
    spell_push_mps:     0 is off. Otherwise, after the dead-run rule and before the merge, a possession shorter
                        than spell_push_frames whose mean Half.push_mps toward its own team is at most
                        -spell_push_mps goes to the other team, every such possession judged on the codes as
                        they stand before any flip. The team in possession pushes toward the goal it attacks;
                        judging whole possessions keeps the push from flipping frames one by one.
    spell_push_frames:  the length limit for spell_push_mps; set together with it.
    spell_push_between: 1 flips only possessions whose two neighbours are possessions of the other team.
                        Needs spell_push_mps.
    spell_push_unseen:  0 is off. Otherwise only a possession whose share of frames with no token is at least
                        this is judged, on the inference (not measured) that push trails a turnover, so where
                        the ball was seen the token decides. Needs spell_push_mps.
    switch_penalty:     0 is off. Otherwise "marginal" takes the block labels that maximise the summed
                        log posterior minus switch_penalty per change of team (_penalized_path) instead of
                        each block's argmax, so a run of one team inside the other survives only when its
                        summed log-odds over that team reach 2 * switch_penalty. A pass through D between
                        the teams is charged once. "marginal" only.
    switch_contact_penalty: 0 is off. Otherwise a change of team into a block where some frame has contact costs
                        this instead of switch_penalty. Contact is both teams' nearest players within
                        switch_contact_m of the ball, or the ball faster than switch_contact_mps, so a turnover
                        the tracking can see is cheap and a change inside a ball gap is not. Needs switch_penalty
                        and switch_contact_m, and a Half with geometry.
    switch_contact_m:   see switch_contact_penalty.
    switch_contact_mps: see switch_contact_penalty; 0 leaves the speed cue off.
    spell_flip_p:       0 is off. Otherwise, after the merge and before the lag, a possession shorter than
                        spell_flip_frames whose share of frames with a token is at least spell_flip_seen goes to
                        the other team when the logistic spell_logit over its SPELL_FEATURES (_spell_runs) gives
                        P(flip) >= spell_flip_p, every such possession judged on the codes as they stand before
                        any flip. The weights were fitted on dev labels to say when giving a short possession
                        away gains matched possessions. "marginal" only: one feature is the chain's log-odds.
    spell_flip_frames:  the length limit for spell_flip_p; set together with it.
    spell_flip_seen:    the token share a possession needs to be judged by spell_flip_p; 0 judges all.
    spell_logit:        {"a": intercept, feature: weight} over SPELL_FEATURES, a feature left out weighing 0;
                        set exactly when spell_flip_p is.
    spell_flip_adjacent: with spell_flip_p, of the passing possessions that share a boundary only the one with
                        the highest spell logit goes to the other team, then the next highest touching no kept
                        one, and so on (ties to the earlier start): flipping both sides of a boundary only moves
                        it. False flips every passing possession.

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
    dead_still_mps: float = 0.0
    dead_still_frames: int = 0
    dead_pace_still_mps: float = 0.0
    dead_pace_live_mps: float = 0.0
    handover_lag: int = 0
    spell_merge_frames: int = 0
    spell_merge_tails: int = 0
    spell_push_mps: float = 0.0
    spell_push_frames: int = 0
    spell_push_between: int = 0
    spell_push_unseen: float = 0.0
    switch_penalty: float = 0.0
    switch_contact_penalty: float = 0.0
    switch_contact_m: float = 0.0
    switch_contact_mps: float = 0.0
    spell_flip_p: float = 0.0
    spell_flip_frames: int = 0
    spell_flip_seen: float = 0.0
    spell_logit: Mapping[str, float] = dataclasses.field(default_factory=dict)
    dead_lead_cut: int = 0
    dead_out_lead_cut: int = 0
    dead_out_min_run: int = 0
    spell_flip_adjacent: bool = False
    dead_line_m: float = 0.0
    dead_line_min_run: int = 0
    dead_line_lead_cut: int = 0
    dead_end_lead: int = 0
    dead_return_m: float = 0.0
    dead_return_min_run: int = 0
    dead_end_live_mps: float = 0.0
    dead_end_cut: int = 0

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
        _number("dead_lead_cut", self.dead_lead_cut, 0, self.dead_trim, integer=True, lo_open=False, hi_open=False)
        _number("dead_end_cut", self.dead_end_cut, 0, self.dead_trim, integer=True, lo_open=False, hi_open=False)
        _number("dead_out_lead_cut", self.dead_out_lead_cut, 0, self.dead_trim, integer=True, lo_open=False,
                hi_open=False)
        _number("dead_out_min_run", self.dead_out_min_run, 0, self.dead_min_run, integer=True, lo_open=False,
                hi_open=False)
        _number("dead_line_m", self.dead_line_m, 0, math.inf, lo_open=False)
        _number("dead_line_min_run", self.dead_line_min_run, 0, self.dead_min_run, integer=True, lo_open=False,
                hi_open=False)
        if bool(self.dead_line_m) != bool(self.dead_line_min_run):
            raise ValueError("dead_line_m and dead_line_min_run act together: set both or neither")
        _number("dead_line_lead_cut", self.dead_line_lead_cut, 0, self.dead_trim, integer=True, lo_open=False,
                hi_open=False)
        _number("dead_end_lead", self.dead_end_lead, 0, math.inf, integer=True, lo_open=False)
        _number("dead_end_live_mps", self.dead_end_live_mps, 0, math.inf, lo_open=False)
        _number("dead_return_m", self.dead_return_m, 0, math.inf, lo_open=False)
        _number("dead_return_min_run", self.dead_return_min_run, 0, math.inf, integer=True, lo_open=False)
        if bool(self.dead_return_m) != bool(self.dead_return_min_run):
            raise ValueError("dead_return_m and dead_return_min_run act together: set both or neither")
        if bool(self.dead_end_lead) != bool(self.dead_end_live_mps):
            raise ValueError("dead_end_lead and dead_end_live_mps act together: set both or neither")
        if self.dead_line_lead_cut and not self.dead_line_m:
            raise ValueError("dead_line_lead_cut reads dead_line_m and acts only with it > 0")
        if (self.dead_out_lead_cut or self.dead_out_min_run) and not self.dead_outside_m:
            raise ValueError("dead_out_lead_cut and dead_out_min_run read dead_outside_m and act only with it > 0")
        _number("dead_outside_m", self.dead_outside_m, 0, math.inf, lo_open=False)
        _number("dead_still_mps", self.dead_still_mps, 0, math.inf, lo_open=False)
        _number("dead_still_frames", self.dead_still_frames, 0, math.inf, integer=True, lo_open=False)
        _number("dead_pace_still_mps", self.dead_pace_still_mps, 0, math.inf, lo_open=False)
        _number("dead_pace_live_mps", self.dead_pace_live_mps, 0, math.inf, lo_open=False)
        _number("handover_lag", self.handover_lag, 0, math.inf, integer=True, lo_open=False)
        _number("spell_merge_frames", self.spell_merge_frames, 0, math.inf, integer=True, lo_open=False)
        _number("spell_merge_tails", self.spell_merge_tails, 0, 1, integer=True, lo_open=False, hi_open=False)
        if self.spell_merge_tails and not self.spell_merge_frames:
            raise ValueError("spell_merge_tails acts only with spell_merge_frames > 0")
        _number("spell_push_mps", self.spell_push_mps, 0, math.inf, lo_open=False)
        _number("spell_push_frames", self.spell_push_frames, 0, math.inf, integer=True, lo_open=False)
        _number("spell_push_between", self.spell_push_between, 0, 1, integer=True, lo_open=False, hi_open=False)
        if bool(self.spell_push_mps) != bool(self.spell_push_frames):
            raise ValueError("spell_push_mps and spell_push_frames are set together")
        _number("spell_push_unseen", self.spell_push_unseen, 0, 1, lo_open=False, hi_open=False)
        if (self.spell_push_between or self.spell_push_unseen) and not self.spell_push_mps:
            raise ValueError("spell_push_between and spell_push_unseen act only with spell_push_mps > 0")
        _number("switch_penalty", self.switch_penalty, 0, math.inf, lo_open=False)
        if self.switch_penalty and self.decode_rule != "marginal":
            raise ValueError("switch_penalty acts only with decode_rule 'marginal'")
        _number("switch_contact_penalty", self.switch_contact_penalty, 0, math.inf, lo_open=False)
        _number("switch_contact_m", self.switch_contact_m, 0, math.inf, lo_open=False)
        _number("switch_contact_mps", self.switch_contact_mps, 0, math.inf, lo_open=False)
        if bool(self.switch_contact_penalty) != bool(self.switch_contact_m):
            raise ValueError("switch_contact_penalty and switch_contact_m are set together")
        if (self.switch_contact_penalty or self.switch_contact_mps) and not (self.switch_penalty and self.switch_contact_m):
            raise ValueError("switch_contact_penalty and switch_contact_mps act only with switch_penalty > 0 and switch_contact_m > 0")
        _number("spell_flip_p", self.spell_flip_p, 0, 1, lo_open=False)
        _number("spell_flip_frames", self.spell_flip_frames, 0, math.inf, integer=True, lo_open=False)
        _number("spell_flip_seen", self.spell_flip_seen, 0, 1, lo_open=False, hi_open=False)
        if not (bool(self.spell_flip_p) == bool(self.spell_flip_frames) == bool(self.spell_logit)):
            raise ValueError("spell_flip_p, spell_flip_frames and spell_logit are set together")
        if self.spell_flip_seen and not self.spell_flip_p:
            raise ValueError("spell_flip_seen acts only with spell_flip_p > 0")
        if not isinstance(self.spell_flip_adjacent, bool):
            raise ValueError(f"spell_flip_adjacent must be true or false, got {self.spell_flip_adjacent!r}")
        if self.spell_flip_adjacent and not self.spell_flip_p:
            raise ValueError("spell_flip_adjacent acts only with spell_flip_p > 0")
        if self.spell_logit:
            if "a" not in self.spell_logit or not set(self.spell_logit) <= {"a", *SPELL_FEATURES}:
                raise ValueError(f"spell_logit needs 'a' and takes only {', '.join(SPELL_FEATURES)}")
            for name, w in self.spell_logit.items():
                _number(f"spell_logit[{name}]", w, -math.inf, math.inf)
            if self.decode_rule != "marginal":
                raise ValueError("spell_flip_p acts only with decode_rule 'marginal'")
        if bool(self.dead_still_mps) != bool(self.dead_still_frames):
            raise ValueError("dead_still_mps and dead_still_frames are set together")
        if self.dead_min_run and 2 * self.dead_trim >= self.dead_min_run:
            raise ValueError("dead_trim must leave part of a dead_min_run run: 2 * dead_trim < dead_min_run")
        if not self.dead_min_run and any(getattr(self, f) for f in _DEAD_RULE_FIELDS):
            raise ValueError(f"{', '.join(_DEAD_RULE_FIELDS)} act only with dead_min_run > 0")
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
_OPTIONAL_EMISSION = dict.fromkeys(_LOGIT_FIELDS, 0.0)
_OPTIONAL_PARAMS = {"dead_min_run": 0, "dead_trim": 0, "dead_close": 0, "dead_outside_m": 0.0, "dead_still_mps": 0.0,
                    "dead_still_frames": 0, "dead_pace_still_mps": 0.0, "dead_pace_live_mps": 0.0, "handover_lag": 0,
                    "spell_merge_frames": 0, "spell_merge_tails": 0, "spell_push_mps": 0.0, "spell_push_frames": 0,
                    "spell_push_between": 0, "spell_push_unseen": 0.0, "switch_penalty": 0.0, "switch_contact_penalty": 0.0,
                    "switch_contact_m": 0.0, "switch_contact_mps": 0.0, "spell_flip_p": 0.0,
                    "spell_flip_frames": 0, "spell_flip_seen": 0.0, "spell_logit": {}, "dead_lead_cut": 0,
                    "dead_out_lead_cut": 0, "dead_out_min_run": 0, "spell_flip_adjacent": False,
                    "dead_line_m": 0.0, "dead_line_min_run": 0, "dead_line_lead_cut": 0, "dead_end_lead": 0,
                    "dead_end_live_mps": 0.0, "dead_return_m": 0.0,
                    "dead_return_min_run": 0, "dead_end_cut": 0}
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
             round(posterior, 9), or with switch_penalty the penalized path over it. The rounding makes
             exact symmetric ties (a flat block at the start of a half) resolve to the lower label on
             every machine instead of on 1-ulp noise.
          4. dead_min_run > 0 replaces the chain's D by the missing-run rule (see DecoderParams).
          5. spell_push_mps gives short possessions that push contradicts to the other team.
          6. spell_merge_frames joins short possessions to their neighbours (see DecoderParams).
          7. spell_flip_p gives short possessions its fitted logistic picks to the other team.
          8. handover_lag moves the hand-overs between the teams later (see DecoderParams).
          With switch_penalty, or after 4 to 8, the posterior is dropped, because it no longer describes the
          codes.
        """
        p, kickoff = self.params, half.id.kickoff
        ev = self.emission.loglik(half)[kickoff:].astype(np.float64)
        m = ev.shape[0]
        E = p.temper * np.add.reduceat(ev, np.arange(0, m, p.stride), axis=0)
        if p.decode_rule == "map":
            codes = np.full(half.n, D, dtype=np.int8)
            codes[kickoff:] = np.repeat(_map(E, p), p.stride)[:m]
            return Decoded(codes=_rules(codes, half, p), posterior=None)
        g = _forward_backward(E, _chain(p))
        logodds = _frame_logodds(g, half, p.stride, m) if p.spell_flip_p else None
        if p.switch_penalty:
            codes = np.full(half.n, D, dtype=np.int8)
            lam = _switch_costs(half, p, kickoff, m) if p.switch_contact_penalty else p.switch_penalty
            codes[kickoff:] = np.repeat(_penalized_path(g, lam), p.stride)[:m]
            return Decoded(codes=_rules(codes, half, p, logodds), posterior=None)
        post = np.empty((half.n, 3), dtype=np.float64)
        post[:kickoff] = (0.0, 0.0, 1.0)
        post[kickoff:] = np.repeat(g, p.stride, axis=0)[:m]
        codes = np.round(post, 9).argmax(axis=1).astype(np.int8)
        if p.dead_min_run or p.handover_lag or p.spell_merge_frames or p.spell_push_mps or p.spell_flip_p:
            return Decoded(codes=_rules(codes, half, p, logodds), posterior=None)
        return Decoded(codes=codes, posterior=post.astype(np.float32))

    @property
    def needs_geometry(self) -> bool:
        """True when decoding reads Half.geometry, Half.pace_mps or Half.push_mps, which only challenge.observe
        supplies."""
        p = self.params
        return self.emission.needs_geometry or bool(p.spell_push_mps or p.spell_flip_p) or bool(p.dead_min_run and (
            p.dead_outside_m or p.dead_still_mps or p.dead_pace_still_mps or p.dead_pace_live_mps))

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


def _rules(codes: NDArray[np.int8], half: Half, p: DecoderParams,
           logodds: NDArray[np.float64] | None = None) -> NDArray[np.int8]:
    flipped = _push_flip(_missing_run_dead(codes, half, p), half, p)
    merged = _merge_spells(flipped, p.spell_merge_frames, p.spell_merge_tails)
    return _lag_handovers(_spell_flip(merged, half, p, logodds), p.handover_lag)


def _frame_logodds(g: NDArray[np.float64], half: Half, stride: int, m: int) -> NDArray[np.float64]:
    """Per frame, ln P(H) - ln P(A) of the block posterior rounded to 9 places (floored at 1e-12); 0 before
    kickoff."""
    h, a = np.maximum(np.round(g[:, 0], 9), 1e-12), np.maximum(np.round(g[:, 1], 9), 1e-12)
    out = np.zeros(half.n)
    out[half.id.kickoff:] = np.repeat(np.log(h) - np.log(a), stride)[:m]
    return out


def _spell_runs(codes: NDArray[np.int8], half: Half, frames: int,
                logodds: NDArray[np.float64]) -> list[tuple[int, int, int, tuple[float, ...]]]:
    """(start, stop, team, SPELL_FEATURES) for each team run of codes after kickoff shorter than frames, every
    feature rounded to 9 places. Means are math.fsum sums, so no feature depends on summation order.

    len: ln(frames / FPS). seen: share of frames with a token. own_tok, other_tok: shares of those frames whose
    token is the run's team, the other team. closest_own: ln(1 + the nearest distance on own-token frames,
    capped at 10 m). speed_med, speed_max: ln(1 + median, max ball speed on seen frames, max capped at 40 m/s).
    margin_own: ln(1 + median team margin on own-token frames, capped at 30 m). push: mean push toward the run's
    team, clipped to +-5 m/s. logodds: mean chain log-odds toward the run's team, clipped to +-20. sandwiched: 1
    when both neighbouring runs are the other team. prev_len, next_len: ln(1 + neighbour length). next_to_d: 1
    when a neighbour is D (the half's edges count as D). touch_own, touch_other: ln(1 + the largest change of ball
    speed between frames t - 5 and t + 5, capped at 40 m/s, over frames t within 1.5 m of a player whose token is
    the run's team inside the run, the other team's within 25 frames of it); 0 when there is none. rel_own:
    ln(1 + median ball speed relative to the nearest player on own-token frames, capped at 40 m/s); 0 when there
    is none or the geometry has no rel_mps. shape_own: mean Half.shape_lo toward the run's team over frames
    [start + 50, stop + 50), because team shape trails a change of possession by 2 to 4 s; 0 when none is
    present or the Half has no shape_lo. held_own: share of the run's frames whose held team is the run's team,
    the held team being the token at the latest frame up to then with the nearest player within 1 m of the ball
    (experiment 35's last team within 1 m); a frame with no such earlier frame counts as not own. goal_own,
    goal_other: mean of sign(u) ln(1 + |u|), u = BallGeometry.goal_mps clipped to +-40 m/s, over the run's
    own-token frames and over its other-token frames; positive means the ball moves toward the goal of the
    token's team; 0 when there is none or the geometry has no goal_mps. kick_own, kick_other: touch_own and
    touch_other with the change of the ball's velocity vector (vx_mps, vy_mps) in place of the change of its
    speed, so a redirect at equal speed counts; 0 when there is none or the geometry has no vx_mps.
    """
    g = half.geometry
    if g is None or half.push_mps is None:
        raise ValueError(f"{half.id}: spell_flip_p reads Half.geometry and Half.push_mps and the Half has none; "
                         "observe it from a Geometry (challenge.halves('atd')), not from baseline_raw")
    edges = np.flatnonzero(np.diff(codes)) + 1
    starts, stops = np.r_[0, edges].tolist(), np.r_[edges, half.n].tolist()
    v, s = g.speed_mps.astype(np.float64), _TOUCH_STEP
    dv = np.full(half.n, np.nan)
    if half.n > 2 * s:
        dv[s:-s] = np.abs(v[2 * s:] - v[:-2 * s])
    touch = np.where(g.nearest_m <= _TOUCH_RADIUS_M, np.minimum(dv, _SPEED_CAP_MPS), np.nan)
    kick = None
    if g.vx_mps is not None and g.vy_mps is not None:
        vx, vy = g.vx_mps.astype(np.float64), g.vy_mps.astype(np.float64)
        dk = np.full(half.n, np.nan)
        if half.n > 2 * s:
            dk[s:-s] = np.hypot(vx[2 * s:] - vx[:-2 * s], vy[2 * s:] - vy[:-2 * s])
        kick = np.where(g.nearest_m <= _TOUCH_RADIUS_M, np.minimum(dk, _SPEED_CAP_MPS), np.nan)
    goal = None
    if g.goal_mps is not None:
        u = np.clip(g.goal_mps.astype(np.float64), -_SPEED_CAP_MPS, _SPEED_CAP_MPS)
        goal = np.sign(u) * np.log1p(np.abs(u))
    with np.errstate(invalid="ignore"):
        close = (g.nearest_m <= _HELD_RADIUS_M) & (half.nearest_team != NO_TEAM)
    last = np.maximum.accumulate(np.where(close, np.arange(half.n), -1))
    held = np.where(last >= 0, half.nearest_team[np.maximum(last, 0)], NO_TEAM)
    out = []
    for k, (a, b) in enumerate(zip(starts, stops)):
        team = int(codes[a])
        if team == D or a < half.id.kickoff or b - a >= frames:
            continue
        tok = half.nearest_team[a:b]
        seen, own = tok != NO_TEAM, tok == team
        ns = max(int(seen.sum()), 1)
        near = g.nearest_m[a:b][own].astype(np.float64)
        near = near[~np.isnan(near)]
        speed = g.speed_mps[a:b][seen].astype(np.float64)
        speed = speed[np.isfinite(speed)]
        margin = np.minimum(g.margin_m[a:b][own].astype(np.float64), _MARGIN_CAP_M)
        margin = margin[~np.isnan(margin)]
        push = half.push_mps[a:b].astype(np.float64)
        push = push[np.isfinite(push)]
        rel = (np.minimum(g.rel_mps[a:b][own].astype(np.float64), _SPEED_CAP_MPS) if g.rel_mps is not None
               else np.empty(0))
        rel = rel[~np.isnan(rel)]
        shape = (half.shape_lo[min(a + _SHAPE_LAG, half.n):min(b + _SHAPE_LAG, half.n)].astype(np.float64)
                 if half.shape_lo is not None else np.empty(0))
        shape = shape[~np.isnan(shape)]
        hit = touch[a:b][own]
        hit = hit[~np.isnan(hit)]
        lo, hi = max(a - _TOUCH_SLACK, 0), min(b + _TOUCH_SLACK, half.n)
        miss = touch[lo:hi][half.nearest_team[lo:hi] == 1 - team]
        miss = miss[~np.isnan(miss)]
        gown = goal[a:b][own] if goal is not None else np.empty(0)
        gown = gown[~np.isnan(gown)]
        goth = goal[a:b][tok == 1 - team] if goal is not None else np.empty(0)
        goth = goth[~np.isnan(goth)]
        kown = kick[a:b][own] if kick is not None else np.empty(0)
        kown = kown[~np.isnan(kown)]
        koth = kick[lo:hi][half.nearest_team[lo:hi] == 1 - team] if kick is not None else np.empty(0)
        koth = koth[~np.isnan(koth)]
        sign = 1.0 if team == H else -1.0
        prev = (int(codes[starts[k - 1]]), stops[k - 1] - starts[k - 1]) if k else (D, 0)
        nxt = (int(codes[starts[k + 1]]), stops[k + 1] - starts[k + 1]) if k + 1 < len(starts) else (D, 0)
        x = (math.log((b - a) / FPS), int(seen.sum()) / (b - a), int(own.sum()) / ns,
             int((tok == 1 - team).sum()) / ns,
             math.log1p(min(float(near.min()), 10.0)) if len(near) else math.log1p(10.0),
             math.log1p(float(np.median(speed))) if len(speed) else 0.0,
             math.log1p(min(float(speed.max()), _SPEED_CAP_MPS)) if len(speed) else 0.0,
             math.log1p(float(np.median(margin))) if len(margin) else 0.0,
             min(max(sign * math.fsum(push.tolist()) / len(push), -5.0), 5.0) if len(push) else 0.0,
             min(max(sign * math.fsum(logodds[a:b].tolist()) / (b - a), -20.0), 20.0),
             float(prev[0] == nxt[0] == 1 - team), math.log1p(prev[1]), math.log1p(nxt[1]),
             float(D in (prev[0], nxt[0])), math.log1p(float(hit.max())) if len(hit) else 0.0,
             math.log1p(float(miss.max())) if len(miss) else 0.0,
             math.log1p(float(np.median(rel))) if len(rel) else 0.0,
             sign * math.fsum(shape.tolist()) / len(shape) if len(shape) else 0.0,
             int((held[a:b] == team).sum()) / (b - a),
             math.fsum(gown.tolist()) / len(gown) if len(gown) else 0.0,
             math.fsum(goth.tolist()) / len(goth) if len(goth) else 0.0,
             math.log1p(float(kown.max())) if len(kown) else 0.0,
             math.log1p(float(koth.max())) if len(koth) else 0.0)
        out.append((a, b, team, tuple(round(v, 9) for v in x)))
    return out


def _spell_z(x: tuple[float, ...], w: Mapping[str, float]) -> float:
    """The spell logit a + sum(w * x) over SPELL_FEATURES (a feature W leaves out weighs 0), as an exactly rounded
    math.fsum, rounded to 6 places."""
    return round(math.fsum([w["a"]] + [w[f] * v for f, v in zip(SPELL_FEATURES, x) if f in w]), 6)


_SEEN = SPELL_FEATURES.index("seen")


def _spell_flip(codes: NDArray[np.int8], half: Half, p: DecoderParams,
                logodds: NDArray[np.float64] | None) -> NDArray[np.int8]:
    """Each _spell_runs run with a token share of at least spell_flip_seen takes the other team when its spell
    logit reaches logit(spell_flip_p), both rounded to 6 places; judged on the input runs. With
    spell_flip_adjacent, passing runs that share a boundary are kept by descending logit, then start."""
    if not p.spell_flip_p:
        return codes
    if logodds is None:
        raise ValueError("spell_flip_p needs the chain's frame log-odds; only Decoder.decode supplies them")
    cut = round(math.log(p.spell_flip_p / (1 - p.spell_flip_p)), 6)
    passing = [(a, b, team, z) for a, b, team, x in _spell_runs(codes, half, p.spell_flip_frames, logodds)
               if x[_SEEN] >= p.spell_flip_seen and (z := _spell_z(x, p.spell_logit)) >= cut]
    if p.spell_flip_adjacent:
        kept, starts, stops = [], set(), set()
        for a, b, team, z in sorted(passing, key=lambda r: (-r[3], r[0])):
            if a not in stops and b not in starts:
                kept.append((a, b, team, z))
                starts.add(a)
                stops.add(b)
        passing = kept
    out = codes.copy()
    for a, b, team, _ in passing:
        out[a:b] = 1 - team
    return out


def _push_flip(codes: NDArray[np.int8], half: Half, p: DecoderParams) -> NDArray[np.int8]:
    """Each team run under spell_push_frames whose mean push toward its team is at most -spell_push_mps, judged
    on the input runs, takes the other team; with spell_push_between only between two runs of that team, and
    with spell_push_unseen only when that share of its frames has no token."""
    if not p.spell_push_mps:
        return codes
    if half.push_mps is None:
        raise ValueError(f"{half.id}: spell_push_mps reads Half.push_mps and the Half has none; observe it from a "
                         "Geometry (challenge.halves('atd')), not from baseline_raw")
    edges = np.flatnonzero(np.diff(codes)) + 1
    starts, stops = np.r_[0, edges], np.r_[edges, len(codes)]
    teams = codes[starts]
    out = codes.copy()
    for k, (a, b, team) in enumerate(zip(starts, stops, teams)):
        if team == D or b - a >= p.spell_push_frames:
            continue
        if p.spell_push_between and not (0 < k < len(teams) - 1 and teams[k - 1] == teams[k + 1] == 1 - team):
            continue
        if p.spell_push_unseen and (half.nearest_team[a:b] == NO_TEAM).mean() < p.spell_push_unseen:
            continue
        push = half.push_mps[a:b]
        push = push[np.isfinite(push)].astype(np.float64)
        if len(push) and (push.mean() if team == H else -push.mean()) <= -p.spell_push_mps:
            out[a:b] = 1 - team
    return out


def _merge_spells(codes: NDArray[np.int8], frames: int, tails: int) -> NDArray[np.int8]:
    """Shortest first, a team run under `frames` that follows another team run joins it, together with the
    run after it when that run has the same team; with tails 0 only when a team run follows it."""
    if not frames:
        return codes
    edges = np.flatnonzero(np.diff(codes)) + 1
    runs = [[int(a), int(b), int(codes[a])] for a, b in zip(np.r_[0, edges], np.r_[edges, len(codes)])]
    while True:
        short = [(b - a, k) for k, (a, b, c) in enumerate(runs)
                 if c != D and b - a < frames and k > 0 and runs[k - 1][2] != D
                 and (tails or (k + 1 < len(runs) and runs[k + 1][2] != D))]
        if not short:
            return np.repeat(np.array([c for _, _, c in runs], np.int8), [b - a for a, b, _ in runs])
        k = min(short)[1]
        runs[k - 1][1] = runs[k][1]
        del runs[k]
        if k < len(runs) and runs[k][2] == runs[k - 1][2]:
            runs[k - 1][1] = runs[k][1]
            del runs[k]


def _lag_handovers(codes: NDArray[np.int8], lag: int) -> NDArray[np.int8]:
    """Inside each run of team calls, team[t] = team[max(t - lag, run start)]."""
    if not lag:
        return codes
    live = codes != D
    idx = np.arange(len(codes))
    start = np.maximum.accumulate(np.where(live & ~np.r_[False, live[:-1]], idx, 0))
    out = codes.copy()
    out[live] = codes[np.maximum(idx - lag, start)[live]]
    return out


def _dead_cues(half: Half, p: DecoderParams) -> NDArray[np.bool_]:
    """The frames the dead_min_run rule treats as missing: ball unseen, plus each enabled dead_* cue."""
    unseen = half.nearest_team == NO_TEAM
    if (p.dead_outside_m or p.dead_still_mps) and half.geometry is None:
        raise ValueError(f"{half.id}: dead_outside_m and dead_still_mps read ball geometry and the Half has none; "
                         "observe it from a Geometry (challenge.halves('atd')), not from baseline_raw")
    if p.dead_still_mps:
        slow = np.concatenate(([0], (half.geometry.speed_mps < p.dead_still_mps).view(np.int8), [0]))
        edges = np.flatnonzero(np.diff(slow))
        for start, stop in zip(edges[::2], edges[1::2]):
            if stop - start >= p.dead_still_frames:
                unseen[start:stop] = True
    if (p.dead_pace_still_mps or p.dead_pace_live_mps) and half.pace_mps is None:
        raise ValueError(f"{half.id}: dead_pace_* read Half.pace_mps and the Half has none; observe it from a "
                         "Geometry (challenge.halves('atd')), not from baseline_raw")
    if p.dead_pace_still_mps:
        unseen = unseen | (half.pace_mps < p.dead_pace_still_mps)
    if p.dead_outside_m:
        unseen = unseen | (half.geometry.outside_m > p.dead_outside_m)
    if p.dead_pace_live_mps:
        unseen = unseen & ~(half.pace_mps > p.dead_pace_live_mps)
    return unseen


def _missing_run_dead(codes: NDArray[np.int8], half: Half, p: DecoderParams) -> NDArray[np.int8]:
    if not p.dead_min_run:
        return codes
    kickoff, n = half.id.kickoff, half.n
    team = codes.copy()
    called = np.flatnonzero(team != D)
    if len(called):
        last = np.maximum.accumulate(np.where(team != D, np.arange(n), -1))
        team = np.where(last >= 0, team[np.maximum(last, 0)], team[called[0]]).astype(np.int8)
    unseen = _dead_cues(half, p)
    out = half.geometry.outside_m > p.dead_outside_m if p.dead_out_lead_cut or p.dead_out_min_run else None
    near = None
    if p.dead_line_m:
        if half.geometry is None or half.geometry.line_m is None:
            raise ValueError(f"{half.id}: dead_line_m reads BallGeometry.line_m and this Half has none")
        near = half.geometry.line_m <= p.dead_line_m
    if p.dead_return_m and half.return_m is None:
        raise ValueError(f"{half.id}: dead_return_m reads Half.return_m and this Half has none")
    if p.dead_end_lead and half.pace_mps is None:
        raise ValueError(f"{half.id}: dead_end_lead reads Half.pace_mps and this Half has none")
    missing = np.concatenate(([False], unseen, [False]))
    edges = np.flatnonzero(np.diff(missing.view(np.int8)))
    dead = np.zeros(n + 1, dtype=np.int32)
    tail = p.dead_trim - p.dead_end_cut
    for start, stop in zip(edges[::2], edges[1::2]):
        lead, need = p.dead_trim - p.dead_lead_cut, p.dead_min_run
        if out is not None and out[max(start - _OUT_BEFORE, 0):start + _OUT_AFTER].any():
            lead, need = max(lead - p.dead_out_lead_cut, 0), p.dead_out_min_run or need
        elif near is not None and near[max(start - _OUT_BEFORE, 0):start].any():
            lead, need = max(lead - p.dead_line_lead_cut, 0), p.dead_line_min_run
        if p.dead_return_m:
            far = half.return_m[start:stop]
            if (far >= p.dead_return_m).any():
                need = max(need, p.dead_return_min_run)
        lo = start + lead if start > 0 else -p.dead_min_run
        hi = stop - tail if stop < n else n + p.dead_min_run
        if hi - lo >= need - lead - tail and min(hi, n) > max(lo, 0):
            if p.dead_end_lead and hi < n:
                t = np.arange(max(lo, hi - _END_WINDOW, 0), hi)
                t = t[t + p.dead_end_lead < n]
                fast = t[half.pace_mps[t + p.dead_end_lead] > p.dead_end_live_mps]
                hi = int(fast[0]) if len(fast) else hi
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


def _switch_costs(half: Half, p: DecoderParams, kickoff: int, m: int) -> list[float]:
    """Per block from kickoff, the cost of a change of team into it: switch_contact_penalty where some frame of
    the block has contact (see DecoderParams), else switch_penalty."""
    if half.geometry is None:
        raise ValueError("switch_contact_penalty needs a Half with geometry")
    g = half.geometry
    with np.errstate(invalid="ignore"):
        contact = (g.nearest_m + g.margin_m <= p.switch_contact_m)
        if p.switch_contact_mps:
            contact |= g.speed_mps > p.switch_contact_mps
    hit = np.logical_or.reduceat(contact[kickoff:kickoff + m], np.arange(0, m, p.stride))
    return np.where(hit, p.switch_contact_penalty, p.switch_penalty).tolist()


def _penalized_path(g: NDArray[np.float64], lam: float | list[float]) -> NDArray[np.int8]:
    """Labels over blocks maximising sum log(round(g, 9)) - (cost of each change of team), by Viterbi over H, A,
    D after H and D after A, where D after H may only go back to H or on to A (and the mirror). lam is the cost
    of every change, or a list with the cost of a change into each block. Logs are rounded to 1e-12, as in
    _map; ties keep the current state, then the lower index.
    """
    rows = np.round(np.log(np.maximum(np.round(g, 9), 1e-12)), 12).tolist()
    nb = len(rows)
    costs = lam if isinstance(lam, list) else [lam] * nb
    h, a, dh, da = rows[0][0], rows[0][1], rows[0][2], rows[0][2]
    back = [bytearray(nb) for _ in range(4)]
    bh, ba, bdh, bda = back
    for t in range(1, nb):
        lh, la, ld = rows[t]
        lam = costs[t]
        best, arg = h, 0
        if a - lam > best:
            best, arg = a - lam, 1
        if dh > best:
            best, arg = dh, 2
        if da - lam > best:
            best, arg = da - lam, 3
        nh, bh[t] = best + lh, arg
        best, arg = a, 1
        if h - lam > best:
            best, arg = h - lam, 0
        if dh - lam > best:
            best, arg = dh - lam, 2
        if da > best:
            best, arg = da, 3
        na, ba[t] = best + la, arg
        ndh, bdh[t] = (h + ld, 0) if h > dh else (dh + ld, 2)
        nda, bda[t] = (a + ld, 1) if a > da else (da + ld, 3)
        h, a, dh, da = nh, na, ndh, nda
    final = [h, a, dh, da]
    s, out = final.index(max(final)), bytearray(nb)
    for t in range(nb - 1, 0, -1):
        out[t] = s
        s = back[s][t]
    out[0] = s
    return np.array([H, A, D, D], np.int8)[np.frombuffer(out, np.uint8)]


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
