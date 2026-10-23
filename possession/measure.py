"""Match-wide statistics behind the dropout generator's and the decoder's constants: the real BAR-ATH
ball mask crossed with Smart Tagging, and decoder constants counted on the Metrica labels (other
games). Aggregates only: no function here returns or prints a frame-level row. It reads no ground
truth of the match, and nothing on a decode path imports it."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Literal, NamedTuple, Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray

import games

from . import challenge, dropout, metrica, score
from .challenge import KICKOFF_ROW, SET_PIECES, Tag
from .decoder import Decoder
from .dropout import MissingRates, RunPool
from .half import AWAY, D, FPS, HOME, NO_TEAM

V0 = Path(__file__).resolve().parents[1] / "params" / "tier0_v0.json"

RESTART_KINDS = ("throw-in", "corner kick", "goal kick", "free kick", "kick off (after goal)")
# P(missing) is still 0.64 in [-15, -10) s before a restart (measured), so the dead stretch reaches at
# least this far back; the "phase" complement keeps out of it.
PHASE_GUARD_S = 15.0
LONG_RUN_S = 10
OFFSET_BINS_S = ((-15, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 15))
CONSTANT_RULES = ("m0", "h2p3", "h3p3", "h5p3")
CONSTANT_NAMES = ("q", "alive_share", "p_dead_after_poss", "p_flip_after_dead", "poss_mean_s", "dead_mean_s")
# The one judgement in reading the proxy: at least 35% of a restart lead's rows are dead ball.
PURITY_FLOOR = 0.35
STRESS_WORLD = 11.0


class Zone(IntEnum):
    UNGRADED = 0       # outside games.half_video_blocks: X rows
    PRE_KICKOFF = 1    # graded, before the half's kickoff: D by rule, never decoded
    WINDOW = 2         # graded [kickoff, n): what the decoder reads and the generator's target covers


@dataclass(frozen=True, slots=True)
class Timeline:
    """The real BAR-ATH observation on submission rows [0, challenge.layout().n_total).

    half:    int8 [N]     0 on UNGRADED rows, else 1 or 2.
    zone:    int8 [N]     Zone.
    missing: bool [N]     no nearest-team token (challenge.nearest_team == NO_TEAM), the mask the decoder
                          and the generator's RunPool read: the ATD ball is not observed; False on
                          UNGRADED rows.
    tracked: int8 [N, 2]  players present per side (HOME, AWAY); 0 on UNGRADED rows.
    tags:    challenge.tags().
    Arrays are read-only. Built from automatic sources (ATD, Smart Tagging) and published constants
    (blocks, kickoffs) only.
    """
    half: NDArray[np.int8]
    zone: NDArray[np.int8]
    missing: NDArray[np.bool_]
    tracked: NDArray[np.int8]
    tags: tuple[Tag, ...]


def timeline(data_dir: str | Path | None = None) -> Timeline:
    """IOError when the tactical ATD or Smart Tagging is not on disk."""
    layout = challenge.layout()
    n = layout.n_total
    half, zone = np.zeros(n, np.int8), np.full(n, Zone.UNGRADED, np.int8)
    missing, tracked = np.zeros(n, bool), np.zeros((n, 2), np.int8)
    for h, (block, g) in enumerate(zip(layout.blocks, challenge.load_geometry(data_dir)), start=1):
        rows = slice(block.origin, block.origin + block.n)
        half[rows], zone[rows] = h, Zone.PRE_KICKOFF
        zone[KICKOFF_ROW[h]:rows.stop] = Zone.WINDOW
        missing[rows] = challenge.nearest_team(g) == NO_TEAM
        present = ~np.isnan(g.players_xy[..., 0])
        tracked[rows] = np.stack([present[:, g.slot_team == side].sum(1) for side in (HOME, AWAY)], axis=1)
    for a in (half, zone, missing, tracked):
        a.setflags(write=False)
    return Timeline(half, zone, missing, tracked, challenge.tags(data_dir))


@dataclass(frozen=True, slots=True)
class Proxy:
    """A dead-ball proxy built from Smart Tagging restarts (Tag.restart), and the alive rows it is
    compared with. Both sides lie inside Zone.WINDOW.

    lead_s, tail_s: dead rows [start - lead_s, start + tail_s) of every restart whose kind is in kinds.
    complement:     "rest"  = every other window row.
                    "phase" = those of them under a Tag.phase and outside [start - PHASE_GUARD_S, stop)
                              of every set piece.
    kinds:          restart kinds on the dead side; empty = every restart. The alive side always drops
                    every restart's rows, so per-kind estimates share one alive side.
    """
    lead_s: float
    tail_s: float = 0.0
    complement: Literal["rest", "phase"] = "rest"
    kinds: tuple[str, ...] = ()


# P(missing) by offset from a restart peaks in [-5, 0) s (measured).
HEADLINE = Proxy(lead_s=5.0)
SWEEP: tuple[Proxy, ...] = tuple(Proxy(lead, tail, complement) for lead in (3.0, 5.0, 10.0, 15.0)
                                 for tail in (0.0, 5.0) for complement in ("rest", "phase"))
KIND_PROXIES: tuple[Proxy, ...] = tuple(Proxy(HEADLINE.lead_s, kinds=(kind,)) for kind in RESTART_KINDS)


def estimate(t: Timeline, proxy: Proxy) -> MissingRates:
    window = t.zone == Zone.WINDOW

    def rows(tags: Sequence[Tag]) -> NDArray[np.bool_]:
        return challenge.tag_rows(tags, n_total=len(window), lead_s=proxy.lead_s, tail_s=proxy.tail_s) & window

    restarts = [g for g in t.tags if g.restart]
    every = rows(restarts)
    dead = rows([g for g in restarts if g.kind in proxy.kinds]) if proxy.kinds else every
    alive = window & ~every
    if proxy.complement == "phase":
        alive &= _phase_rows(t)
    return dropout.missing_rates(t.missing, dead=dead, alive=alive)


def estimates(t: Timeline) -> dict[Proxy, MissingRates]:
    """SWEEP, then KIND_PROXIES, in order: every ratio the report prints and the selection bracket
    must hold."""
    return {proxy: estimate(t, proxy) for proxy in (*SWEEP, *KIND_PROXIES)}


def corrected(ratio: float, purity: float) -> float:
    """The dead_bias behind a proxy's ratio when only `purity` of its rows are dead ball and its alive
    side is clean: (ratio - (1 - purity)) / purity. corrected(r, 1.0) == r. Both biases the proxy has
    (untagged stoppages on the alive side, live rows in the lead) pull the ratio toward 1."""
    return (ratio - (1 - purity)) / purity


def implied_purity(ratio: float, rho: float) -> float:
    """The inverse: the share of proxy rows that must be dead ball for world `rho` to show `ratio`,
    (ratio - 1) / (rho - 1)."""
    return (ratio - 1) / (rho - 1)


@dataclass(frozen=True, slots=True)
class Counted:
    """Decoder constants counted on one label rule's Metrica halves over every half's [kickoff, n). A
    report: nothing reads it back into params/ or a default. Raw frequencies, no smoothing.

    q_halves:         per half, (hits, frames) over alive frames whose ball the source file observed
                      (metrica.native_ball_seen) and that have a clean nearest-team token; a hit is a
                      token equal to the label's team.
    poss_*, dead_*:   interior H/A and D segments, i.e. neither the first nor the last of a window.
    poss_before_dead: interior possessions followed by D.
    dead_flips:       interior D segments whose two neighbours (always H or A) differ.
    """
    rule: str
    window_frames: int
    alive_frames: int
    q_halves: tuple[tuple[int, int], ...]
    poss_segments: int
    poss_frames: int
    poss_before_dead: int
    dead_segments: int
    dead_frames: int
    dead_flips: int

    def values(self) -> dict[str, float]:
        """CONSTANT_NAMES, the Decoder.fields() names, to their counted values."""
        hits, frames = (sum(column) for column in zip(*self.q_halves))
        return {"q": hits / frames,
                "alive_share": self.alive_frames / self.window_frames,
                "p_dead_after_poss": self.poss_before_dead / self.poss_segments,
                "p_flip_after_dead": self.dead_flips / self.dead_segments,
                "poss_mean_s": self.poss_frames / self.poss_segments / FPS,
                "dead_mean_s": self.dead_frames / self.dead_segments / FPS}


def counted_constants(rules: Sequence[str] = CONSTANT_RULES,
                      data_dir: str | Path | None = None) -> tuple[Counted, ...]:
    """One Counted per rule key, in order. IOError when the Metrica sample is not on disk."""
    out = []
    for key in rules:
        n = dict.fromkeys(("window_frames", "alive_frames", "poss_segments", "poss_frames", "poss_before_dead",
                           "dead_segments", "dead_frames", "dead_flips"), 0)
        q_halves = []
        for c in metrica.load(metrica.RuleV2.parse(key), data_dir=data_dir):
            k0 = c.id.kickoff
            labels, token = c.labels[k0:], challenge.nearest_team(c.geometry)[k0:]
            alive = labels != D
            seen = alive & metrica.native_ball_seen(c, data_dir)[k0:] & (token != NO_TEAM)
            q_halves.append((int((token[seen] == labels[seen]).sum()), int(seen.sum())))
            n["window_frames"] += len(labels)
            n["alive_frames"] += int(alive.sum())
            segments = score.segments(c.labels, [(k0, c.geometry.n)])
            for before, (lo, hi, code), after in zip(segments, segments[1:-1], segments[2:]):
                if code == D:
                    n["dead_segments"] += 1
                    n["dead_frames"] += hi - lo
                    n["dead_flips"] += int(before[2] != after[2])
                else:
                    n["poss_segments"] += 1
                    n["poss_frames"] += hi - lo
                    n["poss_before_dead"] += int(after[2] == D)
        out.append(Counted(rule=key, q_halves=tuple(q_halves), **n))
    return tuple(out)


class Section(NamedTuple):
    title: str
    table: pd.DataFrame
    notes: tuple[str, ...] = ()

    def render(self) -> str:
        return "\n".join([self.title, self.table.round(4).to_string(index=False), *self.notes])


def tactical_sections(t: Timeline, data_dir: str | Path | None = None) -> list[Section]:
    """The real-match tables: mask, tags, strata, offsets, proxy sweep, run pool, coverage."""
    by_proxy = estimates(t)
    return [_mask_section(t), _tag_section(t), _strata_section(t, by_proxy), _offset_section(t),
            _sweep_section(by_proxy), _pool_section(data_dir), _coverage_section(t)]


def constant_sections(counted: Sequence[Counted], base: Decoder) -> list[Section]:
    """The counted constants beside base's values, and their support."""
    values = pd.DataFrame([{"constant": name, "v0": base.fields()[name], **{c.rule: c.values()[name] for c in counted}}
                           for name in CONSTANT_NAMES])
    support = pd.DataFrame([{"rule": c.rule, "window_frames": c.window_frames, "alive_frames": c.alive_frames,
                             "q_frames": sum(frames for _, frames in c.q_halves),
                             "q_half_min": min(hits / frames for hits, frames in c.q_halves),
                             "q_half_max": max(hits / frames for hits, frames in c.q_halves),
                             "poss_segments": c.poss_segments, "dead_segments": c.dead_segments,
                             "dead_flips": c.dead_flips} for c in counted])
    return [
        Section("decoder constants counted on the Metrica labels (report only; params/ and decoder defaults "
                "unchanged)", values,
                ("q: P(clean nearest-team token == label's team | alive, ball observed in the source file).",
                 "chain constants: interior segments of each half's [kickoff, n); p_flip_after_dead counts D "
                 "stretches whose neighbours differ.")),
        Section("support", support),
    ]


def report(data_dir: str | Path | None = None) -> str:
    """Every section as printable text. The tactical group and the Metrica group each print one skip
    line when their files are absent, so one gate never hides the other."""
    root = Path(data_dir or games.DATA_DIR)
    blocks = []
    try:
        games.require(["atd_meta", "atd_raw", "smart_tagging"], challenge.GAME, data_dir)
    except IOError:
        blocks.append(f"tactical sections  skip: no ATD or Smart Tagging under {root / 'tactical'} "
                      "(set MTAH_DATA_DIR)")
    else:
        blocks += [s.render() for s in tactical_sections(timeline(data_dir), data_dir)]
    try:
        counted = counted_constants(data_dir=data_dir)
    except IOError:
        blocks.append(f"constants  skip: no Metrica sample data under {root / 'metrica_sample'} "
                      "(set MTAH_DATA_DIR or run fetch-metrica)")
    else:
        blocks += [s.render() for s in constant_sections(counted, Decoder.load(V0))]
    return "\n\n".join(blocks)


def _phase_rows(t: Timeline) -> NDArray[np.bool_]:
    n = len(t.zone)
    phase = challenge.tag_rows([g for g in t.tags if g.phase], n_total=n)
    guard = challenge.tag_rows([g for g in t.tags if g.code == SET_PIECES], n_total=n, lead_s=PHASE_GUARD_S)
    return phase & ~guard


def _span(mask: NDArray[np.bool_]) -> slice:
    """[first, last + 1) of a contiguous selection."""
    rows = np.flatnonzero(mask)
    return slice(int(rows[0]), int(rows[-1]) + 1) if rows.size else slice(0, 0)


def _quantiles(name: str, lengths: NDArray[np.int64]) -> dict[str, int | None]:
    q = np.percentile(lengths, (10, 50, 90), method="lower") if lengths.size else (None,) * 3
    return {f"{name}_p{p}": None if v is None else int(v) for p, v in zip((10, 50, 90), q)}


def _mask_section(t: Timeline) -> Section:
    def row(zone: str, half: int | str, spans: Sequence[slice]) -> dict[str, object]:
        parts = [t.missing[s] for s in spans]
        frames, missing = sum(p.size for p in parts), sum(int(p.sum()) for p in parts)
        missing_runs = np.concatenate([dropout.run_lengths(p) for p in parts])
        present_runs = np.concatenate([dropout.run_lengths(~p) for p in parts])
        return {"zone": zone, "half": half, "frames": frames, "missing": missing, "rate": missing / frames,
                "missing_runs": len(missing_runs), "present_runs": len(present_runs),
                **_quantiles("missing", missing_runs), **_quantiles("present", present_runs)}

    window = [_span((t.half == h) & (t.zone == Zone.WINDOW)) for h in (1, 2)]
    pre = [_span((t.half == h) & (t.zone == Zone.PRE_KICKOFF)) for h in (1, 2)]
    rows = [row("window", h, [s]) for h, s in zip((1, 2), window)] + [row("window", "both", window)]
    rows += [row("pre-kickoff", h, [s]) for h, s in zip((1, 2), pre) if s.stop > s.start]
    rows.append(row("graded", "both", [_span(t.half == h) for h in (1, 2)]))
    p = dropout.DropoutParams()
    return Section("ball mask by zone (ATD; run lengths in frames)", pd.DataFrame(rows),
                   (f"generator defaults (DropoutParams): target_missing_rate {p.target_missing_rate:.4f}, "
                    f"prekickoff_missing_rate {p.prekickoff_missing_rate:.4f}",))


def _tag_section(t: Timeline) -> Section:
    groups: dict[tuple[str, str], list[Tag]] = {}
    for g in t.tags:
        groups.setdefault((g.code, g.kind or ""), []).append(g)
    rows = [{"code": code, "kind": kind, "n": len(gs), "home": sum(g.team == HOME for g in gs),
             "away": sum(g.team == AWAY for g in gs), "none": sum(g.team == NO_TEAM for g in gs),
             "median_s": float(np.median([(g.stop - g.start) / FPS for g in gs]))}
            for (code, kind), gs in sorted(groups.items())]
    graded = t.zone != Zone.UNGRADED
    under = challenge.tag_rows(t.tags, n_total=len(graded)) & graded
    return Section("Smart Tagging inventory", pd.DataFrame(rows), (
        f"{len(t.tags)} instances, {len({g.code for g in t.tags})} codes; time base agrees: the kick off (start) "
        f"set pieces contain rows {KICKOFF_ROW[1]} and {KICKOFF_ROW[2]}",
        f"{under.sum() / graded.sum():.1%} of graded rows lie under a tag"))


def _strata_section(t: Timeline, by_proxy: dict[Proxy, MissingRates]) -> Section:
    window = t.zone == Zone.WINDOW
    head = by_proxy[HEADLINE]

    def row(stratum: str, frames: int, missing: int) -> dict[str, object]:
        return {"stratum": stratum, "frames": frames, "missing": missing, "rate": missing / frames,
                "rho_vs_rest": missing / frames / head.p_alive}

    rows = [row(f"restart lead {HEADLINE.lead_s:g} s, every kind", head.dead_frames, head.dead_missing)]
    rows += [row(f"  {p.kinds[0]}", by_proxy[p].dead_frames, by_proxy[p].dead_missing) for p in KIND_PROXIES]
    n = len(window)
    for stratum, mask in (
            ("inside set-piece windows", challenge.tag_rows([g for g in t.tags if g.code == SET_PIECES], n_total=n)),
            ("team phase", challenge.tag_rows([g for g in t.tags if g.phase], n_total=n)),
            ("untagged", ~challenge.tag_rows(t.tags, n_total=n))):
        rows.append(row(stratum, int((mask & window).sum()), int(t.missing[mask & window].sum())))
    rows.append(row("rest of window", head.alive_frames, head.alive_missing))
    return Section("ball missing by stratum (decode window)", pd.DataFrame(rows))


def _offset_section(t: Timeline) -> Section:
    window = t.zone == Zone.WINDOW
    restarts = [g for g in t.tags if g.restart]
    rows = []
    for lo, hi in OFFSET_BINS_S:
        frames = missing = 0
        for g in restarts:
            span = slice(max(0, g.start + lo * FPS), max(0, g.start + hi * FPS))
            inside = window[span]
            frames += int(inside.sum())
            missing += int(t.missing[span][inside].sum())
        rows.append({"offset_s": f"[{lo},{hi})", "frames": frames, "missing": missing, "rate": missing / frames})
    return Section("ball missing by offset from a restart's tag start (each restart counted on its own)",
                   pd.DataFrame(rows))


def _sweep_section(by_proxy: dict[Proxy, MissingRates]) -> Section:
    rows = [{"lead_s": p.lead_s, "tail_s": p.tail_s, "complement": p.complement,
             "dead_frames": r.dead_frames, "dead_missing": r.dead_missing, "alive_frames": r.alive_frames,
             "alive_missing": r.alive_missing, "p_dead": r.p_dead, "p_alive": r.p_alive, "rho": r.ratio,
             "headline": "*" if p == HEADLINE else ""}
            for p, r in ((p, by_proxy[p]) for p in SWEEP)]
    sweep = [by_proxy[p].ratio for p in SWEEP]
    kinds = [by_proxy[p].ratio for p in KIND_PROXIES]
    median = float(np.median(sweep))
    return Section("implied dead_bias by dead-ball proxy definition (decode window)", pd.DataFrame(rows), (
        f"headline {by_proxy[HEADLINE].ratio:.4f}; {len(SWEEP)} definitions {min(sweep):.4f}..{max(sweep):.4f}, "
        f"median {median:.4f}; restart kinds at lead {HEADLINE.lead_s:g} s {min(kinds):.4f}..{max(kinds):.4f}",
        f"purity: world {STRESS_WORLD:g} shows the median only if {implied_purity(median, STRESS_WORLD):.1%} of "
        f"proxy rows are dead ball; at purity {PURITY_FLOOR} the median corrects to "
        f"{corrected(median, PURITY_FLOOR):.2f}"))


def _pool_section(data_dir: str | Path | None) -> Section:
    pools = {"atd": RunPool.from_halves(challenge.halves("atd", data_dir)),
             "baseline_raw": RunPool.from_halves(challenge.halves("baseline_raw"))}
    a, b = pools.values()
    same = all(np.array_equal(getattr(a, f), getattr(b, f)) for f in ("missing", "present", "mask"))
    rows = [{"source": source, "missing_runs": len(p.missing), "present_runs": len(p.present),
             "mask_frames": len(p.mask), "missing_frames": int(p.mask.sum()), "identical": same}
            for source, p in pools.items()]
    return Section("dropout run pool over [kickoff, n): ATD vs baseline_raw", pd.DataFrame(rows))


def _coverage_section(t: Timeline) -> Section:
    window = t.zone == Zone.WINDOW
    missing = t.missing & window
    lengths = dropout.run_lengths(missing)
    long = np.zeros_like(missing)
    long[missing] = np.repeat(lengths >= LONG_RUN_S * FPS, lengths)
    players = t.tracked.sum(axis=1)
    rows = []
    for h in (1, 2):
        half = window & (t.half == h)
        for ball, mask in (("present", half & ~t.missing), ("missing", half & t.missing),
                           (f"missing, run >= {LONG_RUN_S} s", half & long)):
            p = players[mask]
            rows.append({"half": h, "ball": ball, "frames": int(mask.sum()), "players_mean": float(p.mean()),
                         "home_mean": float(t.tracked[mask, HOME].mean()),
                         "away_mean": float(t.tracked[mask, AWAY].mean()),
                         "players_p10": int(np.percentile(p, 10, method="lower")),
                         "players_p50": int(np.percentile(p, 50, method="lower")),
                         "share_ge_18": float((p >= 18).mean())})
    return Section("players tracked (decode window)", pd.DataFrame(rows))
