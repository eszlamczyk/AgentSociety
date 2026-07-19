"""
Converts plan_logs.jsonl into a human-readable per-agent plan timeline.
Plans are grouped by agent and sorted by sim_time. The structure of each
plan (target, steps) is preserved — this is purely a regrouping.

Usage:
    python metrics/readable_plan_log.py plan_logs/plan_logs.jsonl
    python metrics/readable_plan_log.py plan_logs/plan_logs.jsonl --agent 5
    python metrics/readable_plan_log.py plan_logs/plan_logs.jsonl --out plans.txt
    python metrics/readable_plan_log.py plan_logs/plan_logs.jsonl --db agentsociety_data/sqlite.db --exp 60dbd364
    python metrics/readable_plan_log.py plan_logs/plan_logs.jsonl --list-experiments
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from utils.log_utils import find_db, list_experiments, load_profiles, profile_line, sim_sort_key


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_SATISFACTION_LABELS = (
    ("hunger_satisfaction", "hunger"),
    ("energy_satisfaction", "energy"),
    ("safety_satisfaction", "safety"),
    ("social_satisfaction", "social"),
)


def _format_satisfaction(plan: dict) -> str | None:
    before = plan.get("satisfaction_before")
    after = plan.get("satisfaction_after")
    if not before or not after:
        return None
    delta = plan.get("satisfaction_delta") or {}
    parts = []
    for key, label in _SATISFACTION_LABELS:
        if key not in before or key not in after:
            continue
        d = delta.get(key, after[key] - before[key])
        sign = "+" if d >= 0 else ""
        parts.append(f"{label} {before[key]:.2f}->{after[key]:.2f} ({sign}{d:.2f})")
    return "  ".join(parts)


def _format_plan(plan: dict) -> str:
    sim_time    = plan.get("sim_time", "?")
    target      = plan.get("plan_target") or "-"
    need        = plan.get("need") or "-"
    need_before = plan.get("need_before")
    emotion     = plan.get("emotion") or "-"
    n_steps     = plan.get("n_steps", 0)
    n_mob       = plan.get("n_mobility_steps", 0)
    n_dev       = plan.get("n_device_steps", 0)
    has_mob     = plan.get("has_any_mobility", False)
    steps       = plan.get("steps", [])

    mob_flag = "HAS_MOBILITY" if has_mob else "NO_MOBILITY"
    need_str = f"{need_before} -> {need}" if need_before and need_before != need else need
    repeat_flag = "  [SAME NEED REPEATED]" if need_before and need_before == need else ""

    lines = [
        f"  [{sim_time}]  target={target!r}  [{mob_flag}]{repeat_flag}",
        f"               need={need_str}  emotion={emotion}",
        f"               steps={n_steps}  mobility={n_mob}  device={n_dev}",
    ]
    satisfaction_line = _format_satisfaction(plan)
    if satisfaction_line:
        lines.append(f"               satisfaction: {satisfaction_line}")
    for i, s in enumerate(steps, 1):
        intention    = s.get("intention") or "-"
        stype        = s.get("type") or "?"
        device_marker = "  [device]" if s.get("has_device_usage") else ""
        lines.append(f"                 {i}. [{stype:8s}]  {intention}{device_marker}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_timeline(logs: list[dict], profiles: dict[int, dict], agent_filter: int | None) -> str:
    by_agent: dict[int, list[dict]] = defaultdict(list)
    for e in logs:
        by_agent[e["agent_id"]].append(e)

    agent_ids = sorted(by_agent)
    if agent_filter is not None:
        agent_ids = [a for a in agent_ids if a == agent_filter]

    lines = []
    for aid in agent_ids:
        plans = sorted(by_agent[aid], key=lambda e: sim_sort_key(e.get("sim_time", "")))
        name = plans[0].get("agent_name", f"Agent_{aid}")
        n_no_mob = sum(1 for p in plans if not p.get("has_any_mobility", False))

        lines.append("")
        lines.append("=" * 78)
        lines.append(f"  {name}  (id={aid})  |  {len(plans)} plans  ({n_no_mob} with no mobility)")
        lines.append(f"  {profile_line(profiles.get(aid, {}))}")
        lines.append("=" * 78)
        for plan in plans:
            lines.append(_format_plan(plan))
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Human-readable plan log timeline")
    parser.add_argument("path", help="plan_logs.jsonl path or directory containing plan_logs/plan_logs.jsonl")
    parser.add_argument("--agent", type=int, default=None, help="Filter to a single agent id")
    parser.add_argument("--db", default=None, help="Path to sqlite.db (auto-detected if omitted)")
    parser.add_argument("--exp", default="latest",
                        help="Experiment ID, name substring, or 'latest' (default: latest)")
    parser.add_argument("--list-experiments", action="store_true",
                        help="List all experiments in the db and exit")
    parser.add_argument("--out", default=None, help="Write output to a file instead of stdout")
    args = parser.parse_args()

    p = Path(args.path)
    if p.is_dir():
        log_path = p / "plan_logs" / "plan_logs.jsonl"
        search_root = p
    else:
        log_path = p
        search_root = p.parent.parent

    db_path = Path(args.db) if args.db else find_db(search_root)

    if args.list_experiments:
        if db_path and db_path.exists():
            list_experiments(db_path)
        else:
            print("No sqlite.db found. Use --db to specify.")
        return

    with open(log_path) as f:
        logs = [json.loads(l) for l in f if l.strip()]
    print(f"Loaded {len(logs)} plan entries from {log_path}")

    profiles: dict[int, dict] = {}
    if db_path and db_path.exists():
        profiles = load_profiles(db_path, args.exp)
        print(f"Loaded {len(profiles)} agent profiles from {db_path} (exp={args.exp!r})")
    else:
        print("No sqlite.db found — agent headers will have no profile data. Use --db to specify.")

    timeline = build_timeline(logs, profiles, args.agent)

    if args.out:
        Path(args.out).write_text(timeline)
        print(f"Written to {args.out}")
    else:
        print(timeline)


if __name__ == "__main__":
    main()
