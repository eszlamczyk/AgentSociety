"""
Before/after comparison plots for two internet-example runs.

Every figure puts the two runs side by side on *shared axes*, so a bar that
looks twice as tall really is twice as tall. The single-run scripts
(mobility_analysis, activity_analysis, traffic_analysis) autoscale each run
separately, which makes their PNGs misleading when placed next to each other.

Usage:
    python metrics/compare_runs.py BEFORE_DIR AFTER_DIR \
        [--labels "May 2026, no fixes" "Oct 2026, all fixes"] \
        [--agents 100] [--out OUT_DIR] [--include-chat]

Each run dir may use either layout:
    internet/device_usage_logs.jsonl   or  internet_logs/device_usage_logs.jsonl
    positions/position_logs.jsonl      or  position_logs/position_logs.jsonl
    metrics_output/{steps,guardrails}.csv            (optional)

Chat messages: since 2026-10 every real chat send/receive is logged as a
`call` device event with metadata.event = message_sent / message_received.
Older runs never logged those, so they are EXCLUDED from the activity plots
by default (pass --include-chat to keep them). They are still counted in the
summary table and get their own by-hour plot when present.

Outputs (in OUT_DIR, default metrics/output/comparison_<before>_vs_<after>):
    cmp_activity_by_hour.png     stacked actions per hour by type
    cmp_chat_messages_by_hour.png  sent/received chat messages per hour (runs that log them)
    cmp_mobility_by_hour.png     trips per hour (top row), unique agents moving (bottom row)
    cmp_trips_per_agent.png      trips-per-agent histogram incl. the 0-trip (stationary) bucket
    cmp_trip_distance.png        trip distance histogram on shared bins
    cmp_movement_purpose.png     trips by destination purpose
    cmp_top_websites.png         top-N websites overall
    cmp_active_agents_by_hour.png  unique agents online / moving per hour
    cmp_summary.csv              one row per run with the headline numbers
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ---------------------------------------------------------------------------
# Palette: fixed categorical order (validated for adjacent-pair CVD separation).
# Action types always map to the same colour in both runs.
# ---------------------------------------------------------------------------
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
ACTION_ORDER = ["browse", "shop", "work", "social", "stream", "call"]
ACTION_COLOR = {a: SERIES[i] for i, a in enumerate(ACTION_ORDER)}
BEFORE_COLOR, AFTER_COLOR = SERIES[0], SERIES[1]
TEXT_SECONDARY = "#52514e"
HOURS = np.arange(24)
HOUR_LABELS = [f"{h:02d}" for h in range(24)]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _first_existing(run_dir: Path, *candidates: str) -> Path | None:
    for c in candidates:
        p = run_dir / c
        if p.exists():
            return p
    return None


def load_jsonl(path: Path | None) -> list[dict]:
    if path is None:
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def sim_hour(e: dict) -> int:
    return int(e["sim_time"].split(" ")[1].split(":")[0])


def is_chat(e: dict) -> bool:
    ev = (e.get("metadata") or {}).get("event") or ""
    return ev.startswith("message_")


# Plan targets that mean the agent is sleeping or getting ready to. `\brest\b`
# (not "nearest", not "rest of the day") and "wind down" are bedtime routines in
# both runs' vocab ("Relax and prepare for sleep", "Prepare for bed", ...).
_SLEEP_RE = re.compile(r"sleep|\bnap\b|napping|\bbed\b|bedtime|\brest\b(?! of)|wind down", re.I)


def is_sleep_target(text) -> bool:
    return bool(text) and bool(_SLEEP_RE.search(str(text)))


def _sim_secs(sim_time: str) -> int:
    """'day1 02:15:00' -> absolute sim seconds, so plans that straddle midnight
    (the full-day run goes day0 06:00 to day1 05:55) keep their real length."""
    day, clock = sim_time.split(" ")
    h, m, s = clock.split(":")
    return int(day.removeprefix("day")) * 86400 + int(h) * 3600 + int(m) * 60 + int(s)


class Run:
    def __init__(self, run_dir: Path, label: str, n_agents: int | None):
        self.dir = run_dir
        self.label = label
        self.devices = load_jsonl(_first_existing(
            run_dir, "internet/device_usage_logs.jsonl", "internet_logs/device_usage_logs.jsonl"))
        self.positions = load_jsonl(_first_existing(
            run_dir, "positions/position_logs.jsonl", "position_logs/position_logs.jsonl"))
        self.chat = [e for e in self.devices if is_chat(e)]
        self.actions = [e for e in self.devices if not is_chat(e)]
        self.plans = load_jsonl(_first_existing(run_dir, "plan_logs/plan_logs.jsonl"))
        self._sim_end = max((_sim_secs(p["sim_time"]) for p in self.plans), default=0) + 300
        self.n_agents = n_agents or len({e["agent_id"] for e in self.devices}) or 100
        self.steps = self._csv("metrics_output/steps.csv")
        self.guardrails = self._csv("metrics_output/guardrails.csv")

    # -- sleep -------------------------------------------------------------
    def sleep_observed_by_hour(self) -> np.ndarray:
        """Agents with at least one logged device action or trip in the hour
        whose plan target is sleep-related. Available for every run (both
        logs carry the plan target), but undercounts: an agent asleep with no
        device action and no trip is invisible."""
        s = [set() for _ in range(24)]
        for e in self.actions:
            if is_sleep_target(e.get("task_target")):
                s[sim_hour(e)].add(e["agent_id"])
        for e in self.positions:
            if is_sleep_target(e.get("plan_target")):
                s[sim_hour(e)].add(e["agent_id"])
        return np.array([len(x) for x in s])

    def sleep_active_by_hour(self) -> np.ndarray | None:
        """Agents whose *current plan* (from plan_logs, active until the same
        agent's next plan) is sleep-related at any point in the hour. Needs
        plan_logs.jsonl, so None for runs that predate it."""
        if not self.plans:
            return None
        by_agent: dict[int, list[dict]] = defaultdict(list)
        for p in self.plans:
            by_agent[p["agent_id"]].append(p)
        s = [set() for _ in range(24)]
        for aid, ps in by_agent.items():
            ps.sort(key=lambda p: _sim_secs(p["sim_time"]))
            for i, p in enumerate(ps):
                if not is_sleep_target(p.get("plan_target")):
                    continue
                t0 = _sim_secs(p["sim_time"])
                # Active until the agent's next plan; the last plan runs to the
                # end of the run (latest plan timestamp in the log).
                t1 = _sim_secs(ps[i + 1]["sim_time"]) if i + 1 < len(ps) else self._sim_end
                for h in range(t0 // 3600, (max(t1, t0 + 1) - 1) // 3600 + 1):
                    s[h % 24].add(aid)
        return np.array([len(x) for x in s])

    def _csv(self, rel: str) -> list[dict]:
        p = self.dir / rel
        if not p.exists():
            # Aug-23 archive nests metrics_output/<experiment>/steps.csv
            hits = sorted(self.dir.glob(rel.replace("metrics_output/", "metrics_output/*/")))
            if not hits:
                return []
            p = hits[0]
        with open(p) as f:
            return list(csv.DictReader(f))

    # -- derived -----------------------------------------------------------
    def actions_by_hour(self, include_chat: bool) -> dict[str, np.ndarray]:
        src = self.devices if include_chat else self.actions
        counts = {a: np.zeros(24, dtype=int) for a in ACTION_ORDER}
        for e in src:
            a = e["action_type"]
            if a not in counts:
                counts[a] = np.zeros(24, dtype=int)
            counts[a][sim_hour(e)] += 1
        return counts

    def chat_by_hour(self) -> dict[str, np.ndarray]:
        out = {"message_sent": np.zeros(24, dtype=int), "message_received": np.zeros(24, dtype=int)}
        for e in self.chat:
            ev = e["metadata"]["event"]
            out.setdefault(ev, np.zeros(24, dtype=int))[sim_hour(e)] += 1
        return out

    def trips_by_hour(self) -> np.ndarray:
        v = np.zeros(24, dtype=int)
        for e in self.positions:
            v[sim_hour(e)] += 1
        return v

    def movers_by_hour(self) -> np.ndarray:
        s = [set() for _ in range(24)]
        for e in self.positions:
            s[sim_hour(e)].add(e["agent_id"])
        return np.array([len(x) for x in s])

    def online_by_hour(self) -> np.ndarray:
        s = [set() for _ in range(24)]
        for e in self.actions:
            s[sim_hour(e)].add(e["agent_id"])
        return np.array([len(x) for x in s])

    def trips_per_agent(self) -> np.ndarray:
        c = Counter(e["agent_id"] for e in self.positions)
        return np.array([c.get(a, 0) for a in self._agent_ids()])

    def _agent_ids(self) -> list[int]:
        ids = {e["agent_id"] for e in self.devices} | {e["agent_id"] for e in self.positions}
        if len(ids) < self.n_agents:  # pad to declared population
            ids |= set(range(self.n_agents))
        return sorted(ids)[: self.n_agents] if len(ids) > self.n_agents else sorted(ids)

    def distances(self) -> np.ndarray:
        return np.array([e["distance"] for e in self.positions], dtype=float)

    def purposes(self) -> Counter:
        return Counter(_clean_target(e.get("plan_target", "?")) for e in self.positions)

    def websites(self) -> Counter:
        return Counter(e["website"] for e in self.actions if e.get("website"))

    def summary(self) -> dict:
        moving = len({e["agent_id"] for e in self.positions})
        d = self.distances()
        row = {
            "run": self.label,
            "dir": str(self.dir),
            "agents": self.n_agents,
            "device_actions_excl_chat": len(self.actions),
            "chat_messages_sent": sum(1 for e in self.chat if e["metadata"]["event"] == "message_sent"),
            "chat_messages_received": sum(1 for e in self.chat if e["metadata"]["event"] == "message_received"),
            "unique_websites": len(self.websites()),
            "trips": len(self.positions),
            "agents_that_moved": moving,
            "agents_stationary_all_day": self.n_agents - moving,
            "median_trip_distance_m": float(np.median(d)) if len(d) else None,
            "hours_with_any_trip": int((self.trips_by_hour() > 0).sum()),
            "sleep_agent_hours_observed": int(self.sleep_observed_by_hour().sum()),
        }
        active = self.sleep_active_by_hour()
        if active is not None:
            row["sleep_plans_logged"] = sum(1 for p in self.plans if is_sleep_target(p.get("plan_target")))
            row["sleep_agent_hours_from_plans"] = int(active.sum())
            row["sleep_agent_hours_from_plans_09_21"] = int(active[9:21].sum())
        if self.steps:
            row["steps_logged"] = len(self.steps)
            row["wall_time_s_total"] = round(sum(float(r["wall_time_s"]) for r in self.steps), 1)
            row["input_tokens_total"] = int(sum(float(r["input_tokens"]) for r in self.steps))
            row["output_tokens_total"] = int(sum(float(r["output_tokens"]) for r in self.steps))
            row["llm_errors_total"] = int(sum(float(r["total_errors"]) for r in self.steps))
        if self.guardrails:
            row["guardrail_firings_total"] = int(sum(float(r["count"]) for r in self.guardrails))
        return row


def _clean_target(t: str) -> str:
    mapping = {
        "prepare for work": "Work", "begin workday": "Work", "commence work": "Work",
        "start workday": "Work", "work": "Work", "sleep at home": "Sleep/Home",
        "leisure and entertainment": "Leisure", "eat outside": "Eat outside",
    }
    key = str(t).lower().strip()
    # Fold case variants ("Grocery Shopping" / "Grocery shopping") into one bucket.
    return mapping.get(key, key[:1].upper() + key[1:])


# ---------------------------------------------------------------------------
# Figure helpers
# ---------------------------------------------------------------------------

def _style(ax, title: str) -> None:
    ax.set_title(title, fontsize=11, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.set_axisbelow(True)


def _hour_axis(ax) -> None:
    ax.set_xticks(HOURS)
    ax.set_xticklabels(HOUR_LABELS, fontsize=7)
    ax.set_xlabel("Hour of day (sim time)")


def _pair(figsize=(16, 5), nrows=1, sharey="row"):
    fig, axes = plt.subplots(nrows, 2, figsize=figsize, sharey=sharey, squeeze=False)
    return fig, axes


def _save(fig, out_dir: Path, name: str) -> None:
    path = out_dir / name
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Saved {path}")


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------

def plot_activity_by_hour(runs: list[Run], out_dir: Path, include_chat: bool) -> None:
    fig, axes = _pair()
    for ax, run in zip(axes[0], runs):
        counts = run.actions_by_hour(include_chat)
        order = [a for a in ACTION_ORDER if counts[a].sum() > 0] + \
                [a for a in counts if a not in ACTION_ORDER]
        bottom = np.zeros(24)
        for a in order:
            ax.bar(HOURS, counts[a], bottom=bottom, width=0.8, label=a,
                   color=ACTION_COLOR.get(a, SERIES[-1]), edgecolor="white", linewidth=0.8)
            bottom += counts[a]
        total = int(bottom.sum())
        _style(ax, f"{run.label}  ·  {total:,} actions")
        _hour_axis(ax)
    axes[0][0].set_ylabel("Device actions per hour")
    axes[0][1].legend(loc="upper right", fontsize=8, frameon=False, ncol=2)
    note = "incl. chat messages" if include_chat else "chat messages excluded (not logged in older runs)"
    fig.suptitle(f"Online activity by type and hour, {runs[0].n_agents} agents · {note}",
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_activity_by_hour.png")


def plot_chat_by_hour(runs: list[Run], out_dir: Path) -> None:
    if not any(r.chat for r in runs):
        return
    fig, axes = _pair()
    for ax, run in zip(axes[0], runs):
        c = run.chat_by_hour()
        ax.bar(HOURS - 0.2, c["message_sent"], width=0.4, label="sent (plan-driven)",
               color=SERIES[0], edgecolor="white", linewidth=0.5)
        ax.bar(HOURS + 0.2, c["message_received"], width=0.4, label="received (replies)",
               color=SERIES[1], edgecolor="white", linewidth=0.5)
        s, r = int(c["message_sent"].sum()), int(c["message_received"].sum())
        amp = f"{r / s:.1f}x" if s else "n/a"
        title = f"{run.label}  ·  {s} sent, {r} received ({amp})" if run.chat \
            else f"{run.label}  ·  chat traffic not logged in this run"
        _style(ax, title)
        _hour_axis(ax)
    axes[0][0].set_ylabel("Chat messages per hour")
    axes[0][1].legend(loc="upper left", fontsize=8, frameon=False)
    fig.suptitle("Real chat message traffic by hour", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_chat_messages_by_hour.png")


def plot_mobility_by_hour(runs: list[Run], out_dir: Path) -> None:
    fig, axes = _pair(figsize=(16, 8), nrows=2)
    for col, run in enumerate(runs):
        trips, movers = run.trips_by_hour(), run.movers_by_hour()
        ax = axes[0][col]
        for a, b in [(7, 9), (16, 19)]:
            ax.axvspan(a - 0.5, b - 0.5, color="#008300", alpha=0.06, lw=0)
        ax.bar(HOURS, trips, width=0.7, color=SERIES[col], edgecolor="white", linewidth=0.5)
        _style(ax, f"{run.label}  ·  {int(trips.sum())} trips")
        ax.set_xticks(HOURS); ax.set_xticklabels([])
        ax = axes[1][col]
        for a, b in [(7, 9), (16, 19)]:
            ax.axvspan(a - 0.5, b - 0.5, color="#008300", alpha=0.06, lw=0)
        ax.bar(HOURS, movers, width=0.7, color=SERIES[col], edgecolor="white", linewidth=0.5)
        _style(ax, f"{run.label}  ·  unique agents moving per hour")
        _hour_axis(ax)
    axes[0][0].set_ylabel("Trips per hour")
    axes[1][0].set_ylabel("Agents moving")
    fig.suptitle(f"Mobility by hour, {runs[0].n_agents} agents (shaded = real-world rush hours)",
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_mobility_by_hour.png")


def plot_trips_per_agent(runs: list[Run], out_dir: Path) -> None:
    per = [r.trips_per_agent() for r in runs]
    top = int(max(p.max() for p in per)) if per else 1
    bins = np.arange(-0.5, top + 1.5, 1)
    fig, axes = _pair(figsize=(14, 5))
    for ax, run, tpa in zip(axes[0], runs, per):
        moving = int((tpa > 0).sum())
        ax.hist(tpa, bins=bins, color=AFTER_COLOR if run is runs[1] else BEFORE_COLOR,
                edgecolor="white", linewidth=0.5)
        _style(ax, f"{run.label}  ·  {moving} moved, {run.n_agents - moving} never moved")
        ax.set_xlabel("Trips per agent over the day (0 = stationary all day)")
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    axes[0][0].set_ylabel("Number of agents")
    fig.suptitle("Trips per agent", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_trips_per_agent.png")


def plot_trip_distance(runs: list[Run], out_dir: Path) -> None:
    ds = [r.distances() for r in runs]
    hi = max((d.max() for d in ds if len(d)), default=1.0)
    bins = np.linspace(0, hi, 31)
    fig, axes = _pair(figsize=(14, 5))
    for ax, run, d in zip(axes[0], runs, ds):
        ax.hist(d, bins=bins, color=AFTER_COLOR if run is runs[1] else BEFORE_COLOR,
                edgecolor="white", linewidth=0.5)
        med = f"median {np.median(d):,.0f} m" if len(d) else "no trips"
        _style(ax, f"{run.label}  ·  n={len(d)}, {med}")
        ax.set_xlabel("Trip distance (m)")
    axes[0][0].set_ylabel("Trips")
    fig.suptitle("Trip distance distribution (shared bins)", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_trip_distance.png")


def plot_movement_purpose(runs: list[Run], out_dir: Path, top_n: int = 12) -> None:
    counters = [r.purposes() for r in runs]
    merged = Counter()
    for c in counters:
        merged.update(c)
    cats = [k for k, _ in merged.most_common(top_n)]
    y = np.arange(len(cats))
    fig, axes = _pair(figsize=(14, max(4, 0.4 * len(cats) + 1.5)), sharey=True)
    xmax = max(c[k] for c in counters for k in cats) if cats else 1
    for ax, run, c in zip(axes[0], runs, counters):
        vals = [c.get(k, 0) for k in cats]
        ax.barh(y, vals, color=AFTER_COLOR if run is runs[1] else BEFORE_COLOR,
                edgecolor="white", linewidth=0.5)
        for yi, v in zip(y, vals):
            if v:
                ax.text(v + xmax * 0.01, yi, str(v), va="center", fontsize=8, color=TEXT_SECONDARY)
        ax.set_xlim(0, xmax * 1.12)
        _style(ax, f"{run.label}")
        ax.grid(axis="y", alpha=0); ax.grid(axis="x", alpha=0.25)
        ax.set_xlabel("Trips")
    axes[0][0].set_yticks(y); axes[0][0].set_yticklabels(cats, fontsize=9)
    axes[0][0].invert_yaxis()
    fig.suptitle("Trips by destination purpose", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_movement_purpose.png")


def plot_top_websites(runs: list[Run], out_dir: Path, top_n: int = 15) -> None:
    counters = [r.websites() for r in runs]
    fig, axes = _pair(figsize=(14, 6), sharey=False)
    xmax = max((v for c in counters for _, v in c.most_common(top_n)), default=1)
    for ax, run, c in zip(axes[0], runs, counters):
        items = c.most_common(top_n)
        names = [k for k, _ in items]
        vals = [v for _, v in items]
        y = np.arange(len(names))
        ax.barh(y, vals, color=AFTER_COLOR if run is runs[1] else BEFORE_COLOR,
                edgecolor="white", linewidth=0.5)
        for yi, v in zip(y, vals):
            ax.text(v + xmax * 0.01, yi, str(v), va="center", fontsize=8, color=TEXT_SECONDARY)
        ax.set_yticks(y); ax.set_yticklabels(names, fontsize=9); ax.invert_yaxis()
        ax.set_xlim(0, xmax * 1.12)
        _style(ax, f"{run.label}  ·  {len(c)} distinct sites")
        ax.grid(axis="y", alpha=0); ax.grid(axis="x", alpha=0.25)
        ax.set_xlabel("Visits")
    fig.suptitle(f"Top {top_n} websites (chat messages excluded)", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_top_websites.png")


def plot_active_agents_by_hour(runs: list[Run], out_dir: Path) -> None:
    fig, axes = _pair()
    for ax, run in zip(axes[0], runs):
        online, movers = run.online_by_hour(), run.movers_by_hour()
        ax.plot(HOURS, online, "-o", color=SERIES[0], lw=2, ms=4, label="online (any device action)")
        ax.plot(HOURS, movers, "-o", color=SERIES[1], lw=2, ms=4, label="moving (trip logged)")
        ax.axhline(run.n_agents, color=TEXT_SECONDARY, ls="--", lw=1, label=f"population ({run.n_agents})")
        ax.set_ylim(0, run.n_agents * 1.08)
        _style(ax, run.label)
        _hour_axis(ax)
    axes[0][0].set_ylabel("Unique agents in the hour")
    handles, labels = axes[0][1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=9, frameon=False,
               bbox_to_anchor=(0.5, -0.04))
    fig.suptitle("Agents online vs. moving, per hour", fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_active_agents_by_hour.png")


def plot_sleep_by_hour(runs: list[Run], out_dir: Path) -> None:
    fig, axes = _pair()
    for col, (ax, run) in enumerate(zip(axes[0], runs)):
        ax.axvspan(-0.5, 5.5, color=TEXT_SECONDARY, alpha=0.06, lw=0)   # 00:00-05:59
        ax.axvspan(21.5, 23.5, color=TEXT_SECONDARY, alpha=0.06, lw=0)  # 22:00-23:59
        observed = run.sleep_observed_by_hour()
        ax.bar(HOURS, observed, width=0.7, color=SERIES[col], edgecolor="white", linewidth=0.5,
               label="in a sleep plan, seen via a logged action or trip")
        active = run.sleep_active_by_hour()
        if active is not None:
            ax.plot(HOURS, active, "-o", color=SERIES[6], lw=2, ms=4,
                    label="current plan is sleep (plan logs, all agents)")
            day_peak = int(active[9:21].max())
            night_mean = active[np.r_[0:6, 22:24]].mean()
            title = f"{run.label}  ·  daytime peak {day_peak}, night mean {night_mean:.0f}"
        else:
            title = f"{run.label}  ·  no plan logs, logged actions/trips only"
        _style(ax, title)
        _hour_axis(ax)
    axes[0][0].set_ylabel("Agents sleeping / going to bed")
    handles, labels = [], []
    for ax in axes[0]:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l not in labels:
                handles.append(h); labels.append(l)
    fig.legend(handles, labels, loc="lower center", ncol=2, fontsize=9, frameon=False,
               bbox_to_anchor=(0.5, -0.04))
    fig.suptitle(f"Agents in a sleep plan by hour, {runs[0].n_agents} agents "
                 "(shaded = 22:00 to 06:00, when they should be asleep)",
                 fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    _save(fig, out_dir, "cmp_sleep_by_hour.png")


def write_summary(runs: list[Run], out_dir: Path) -> None:
    rows = [r.summary() for r in runs]
    keys = list(dict.fromkeys(k for r in rows for k in r))
    path = out_dir / "cmp_summary.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"Saved {path}\n")
    width = max(len(k) for k in keys)
    print(f"{'metric':<{width}}  {rows[0]['run']:>28}  {rows[1]['run']:>28}")
    for k in keys:
        if k in ("run", "dir"):
            continue
        a, b = rows[0].get(k, ""), rows[1].get(k, "")
        fmt = lambda v: f"{v:,.0f}" if isinstance(v, (int, float)) and v is not None else str(v)
        print(f"{k:<{width}}  {fmt(a):>28}  {fmt(b):>28}")


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--labels", nargs=2, metavar=("BEFORE", "AFTER"),
                    default=None, help="Panel titles (default: directory names)")
    ap.add_argument("--agents", type=int, default=None, help="Population size (default: inferred)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--include-chat", action="store_true",
                    help="Keep chat message events in the activity plot")
    args = ap.parse_args()

    before, after = Path(args.before), Path(args.after)
    labels = args.labels or [before.name, after.name]
    runs = [Run(before, labels[0], args.agents), Run(after, labels[1], args.agents)]
    out_dir = args.out or Path(__file__).parent / "output" / f"comparison_{before.name}_vs_{after.name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for r in runs:
        print(f"{r.label}: {len(r.actions)} actions, {len(r.chat)} chat msgs, "
              f"{len(r.positions)} trips, {r.n_agents} agents")

    plot_activity_by_hour(runs, out_dir, args.include_chat)
    plot_chat_by_hour(runs, out_dir)
    plot_mobility_by_hour(runs, out_dir)
    plot_trips_per_agent(runs, out_dir)
    plot_trip_distance(runs, out_dir)
    plot_movement_purpose(runs, out_dir)
    plot_top_websites(runs, out_dir)
    plot_active_agents_by_hour(runs, out_dir)
    plot_sleep_by_hour(runs, out_dir)
    write_summary(runs, out_dir)


if __name__ == "__main__":
    main()
