"""
Activity analysis plots for a full-day run.

Plots:
  1. Activity type distribution by hour (stacked bar histogram)
  2. Agent movement by hour (moving vs. stationary)

Usage:
    python metrics/activity_analysis.py run_logs/100agent_fullday
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _parse_sim_hour(sim_time: str) -> int:
    """'day0 14:35:01' -> 14"""
    time_part = sim_time.split(" ")[1]   # '14:35:01'
    return int(time_part.split(":")[0])


def load_device_logs(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f]


def load_position_logs(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f]


# ---------------------------------------------------------------------------
# Plot 1 — activity type per hour (stacked bar)
# ---------------------------------------------------------------------------

def plot_activity_by_hour(logs: list[dict], out_dir: Path) -> None:
    # Count actions per hour per type
    action_types = sorted({e["action_type"] for e in logs})
    counts: dict[str, list[int]] = {a: [0] * 24 for a in action_types}

    for e in logs:
        hour = _parse_sim_hour(e["sim_time"])
        counts[e["action_type"]][hour] += 1

    hours = list(range(24))
    x = np.arange(24)

    fig, ax = plt.subplots(figsize=(14, 5))
    bottom = np.zeros(24)
    for action in action_types:
        vals = np.array(counts[action])
        ax.bar(x, vals, bottom=bottom, label=action, width=0.8)
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}:00" for h in hours], rotation=45, ha="right", fontsize=8)
    ax.set_xlabel("Hour of day (sim time)")
    ax.set_ylabel("Number of actions")
    ax.set_title("Agent activity type by hour — 100 agents, full day")
    ax.legend(loc="upper right")
    fig.tight_layout()

    path = out_dir / "activity_by_hour.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot 2 — movement by hour (agents moving vs. stationary)
# ---------------------------------------------------------------------------

def plot_movement_by_hour(device_logs: list[dict], position_logs: list[dict],
                           n_agents: int, out_dir: Path) -> None:
    # Count unique agents moving each hour from position logs
    moving_agents: dict[int, set] = defaultdict(set)
    for e in position_logs:
        hour = _parse_sim_hour(e["sim_time"])
        moving_agents[hour].add(e["agent_id"])

    # Count unique agents active (any internet action) each hour
    active_agents: dict[int, set] = defaultdict(set)
    for e in device_logs:
        hour = _parse_sim_hour(e["sim_time"])
        active_agents[hour].add(e["agent_id"])

    hours = list(range(24))
    x = np.arange(24)
    moving = np.array([len(moving_agents.get(h, set())) for h in hours])
    active = np.array([len(active_agents.get(h, set())) for h in hours])
    stationary_active = np.clip(active - moving, 0, None)

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.bar(x, moving, label="Moving (position change logged)", width=0.8, color="tab:orange")
    ax.bar(x, stationary_active, bottom=moving, label="Active online (stationary)", width=0.8, color="tab:blue")
    ax.axhline(n_agents, color="red", linestyle="--", linewidth=1, label=f"Total agents ({n_agents})")

    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:02d}:00" for h in hours], rotation=45, ha="right", fontsize=8)
    ax.set_xlabel("Hour of day (sim time)")
    ax.set_ylabel("Number of agents")
    ax.set_title("Agent movement vs. online activity by hour — 100 agents, full day")
    ax.legend(loc="upper right")
    fig.tight_layout()

    path = out_dir / "movement_by_hour.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", help="Run directory (contains internet/ and positions/ subdirs)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    device_log_path   = run_dir / "internet" / "device_usage_logs.jsonl"
    position_log_path = run_dir / "positions" / "position_logs.jsonl"
    out_dir = run_dir / "plots"
    out_dir.mkdir(exist_ok=True)

    device_logs   = load_device_logs(device_log_path)
    position_logs = load_position_logs(position_log_path)
    n_agents = len({e["agent_id"] for e in device_logs})

    plot_activity_by_hour(device_logs, out_dir)
    plot_movement_by_hour(device_logs, position_logs, n_agents, out_dir)


if __name__ == "__main__":
    main()
