"""
Converts position_logs.jsonl into a human-readable per-agent timeline.

Agent headers include profile fields (age, gender, occupation, etc.) loaded
from the simulation's SQLite database when available.

Usage:
    python metrics/readable_log.py plan_logs/position_logs.jsonl
    python metrics/readable_log.py plan_logs/position_logs.jsonl --agent 5
    python metrics/readable_log.py plan_logs/position_logs.jsonl --out timeline.txt
    python metrics/readable_log.py plan_logs/position_logs.jsonl --db agentsociety_data/sqlite.db --exp 60dbd364
    python metrics/readable_log.py plan_logs/position_logs.jsonl --list-experiments
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from utils.log_utils import find_db, list_experiments, load_profiles, profile_line, sim_sort_key


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_entry(e: dict) -> str:
    sim_time  = e.get("sim_time", "?")
    plan      = e.get("plan_target") or "-"
    intention = e.get("step_intention") or "-"
    stype     = e.get("step_type") or "?"
    emotion   = e.get("emotion") or "-"
    need      = e.get("need") or "-"
    dist      = e.get("distance", 0)
    conn      = e.get("connectivity", "?")
    fx, fy    = e["from"]["x"], e["from"]["y"]
    tx, ty    = e["to"]["x"],   e["to"]["y"]

    return (
        f"  [{sim_time}]  plan={plan!r}  intention={intention!r}  type={stype}\n"
        f"               emotion={emotion}  need={need}\n"
        f"               ({fx:+.0f},{fy:+.0f}) -> ({tx:+.0f},{ty:+.0f})  dist={dist:.0f}m  conn={conn}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_timeline(logs: list[dict], profiles: dict[int, dict], agent_filter: int | None) -> str:
    by_agent: dict[int, list[dict]] = defaultdict(list)
    for e in logs:
        by_agent[e["agent_id"]].append(e)

    agent_ids = sorted(set(by_agent) | set(profiles))
    if agent_filter is not None:
        agent_ids = [a for a in agent_ids if a == agent_filter]

    lines = []
    for aid in agent_ids:
        entries = sorted(by_agent.get(aid, []), key=lambda e: sim_sort_key(e.get("sim_time", "")))
        name = entries[0].get("agent_name", f"Agent_{aid}") if entries else f"Agent_{aid}"
        total_dist = sum(e.get("distance", 0) for e in entries)
        no_move = "  [NO MOVEMENT]" if not entries else ""

        lines.append("")
        lines.append("=" * 78)
        lines.append(f"  {name}  (id={aid})  |  {len(entries)} moves  {total_dist:.0f}m total{no_move}")
        lines.append(f"  {profile_line(profiles.get(aid, {}))}")
        lines.append("=" * 78)
        for e in entries:
            lines.append(_format_entry(e))
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Human-readable position log timeline")
    parser.add_argument("path", help="position_logs.jsonl path or directory containing positions/position_logs.jsonl")
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
        log_path = p / "positions" / "position_logs.jsonl"
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
    print(f"Loaded {len(logs)} position entries from {log_path}")

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
