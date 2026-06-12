"""
Spatial mobility analysis for internet simulation runs.

Usage:
    python metrics/mobility_analysis.py run_logs/100agent_fullday
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np


def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def _parse_sim_hour(sim_time: str) -> int:
    return int(sim_time.split(" ")[1].split(":")[0])


def _clean_target(t: str) -> str:
    mapping = {
        "prepare for work": "Work",
        "begin workday": "Work",
        "commence work": "Work",
        "start workday": "Work",
        "work": "Work",
        "sleep at home": "Sleep/Home",
        "leisure and entertainment": "Leisure",
        "eat outside": "Eat outside",
    }
    return mapping.get(t.lower().strip(), t)


def plot_trajectories(logs: list[dict], out_dir: Path) -> None:
    targets = sorted({_clean_target(e["plan_target"]) for e in logs})
    cmap = plt.get_cmap("tab10")
    color_map = {t: cmap(i / max(len(targets) - 1, 1)) for i, t in enumerate(targets)}

    fig, ax = plt.subplots(figsize=(10, 10))

    for e in logs:
        fx, fy = e["from"]["x"], e["from"]["y"]
        tx, ty = e["to"]["x"],   e["to"]["y"]
        color = color_map[_clean_target(e["plan_target"])]
        ax.annotate("",
                    xy=(tx, ty), xytext=(fx, fy),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.0, mutation_scale=8))

    all_from_x = [e["from"]["x"] for e in logs]
    all_from_y = [e["from"]["y"] for e in logs]
    ax.scatter(all_from_x, all_from_y, c="black", s=10, zorder=5, alpha=0.5)

    from matplotlib.lines import Line2D
    legend_elems = [Line2D([0], [0], color=color_map[t], lw=2, label=t) for t in targets]
    ax.legend(handles=legend_elems, loc="upper right", fontsize=9)

    ax.set_xlabel("X coordinate (m)")
    ax.set_ylabel("Y coordinate (m)")
    ax.set_title("Agent movement trajectories coloured by destination purpose")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    path = out_dir / "mobility_trajectories.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


def plot_distance_distribution(logs: list[dict], out_dir: Path) -> None:
    distances = np.array([e["distance"] for e in logs])

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(distances, bins=30, color="tab:blue", edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Trip distance (m)")
    ax.set_ylabel("Count")
    ax.set_title("Trip distance distribution")
    stats = (f"n={len(distances)}  min={distances.min():.0f}m  max={distances.max():.0f}m  "
             f"mean={distances.mean():.0f}m  median={np.median(distances):.0f}m")
    ax.text(0.98, 0.95, stats, transform=ax.transAxes,
            ha="right", va="top", fontsize=8,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.7))
    fig.tight_layout()

    path = out_dir / "mobility_distance_dist.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


def plot_mobility_by_hour(logs: list[dict], n_total_agents: int, out_dir: Path) -> None:
    trip_count = [0] * 24
    moving_agents = [set() for _ in range(24)]

    for e in logs:
        h = _parse_sim_hour(e["sim_time"])
        trip_count[h] += 1
        moving_agents[h].add(e["agent_id"])

    x = np.arange(24)
    unique_moving = [len(moving_agents[h]) for h in range(24)]

    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax2 = ax1.twinx()

    bars = ax1.bar(x, trip_count, color="tab:blue", alpha=0.7, width=0.6, label="Trips")
    line, = ax2.plot(x, unique_moving, "o-", color="tab:orange", linewidth=2,
                     markersize=5, label="Unique agents moving")

    for rush_start, rush_end in [(7, 9), (16, 19)]:
        ax1.axvspan(rush_start - 0.5, rush_end - 0.5, color="green", alpha=0.08,
                    label="IRL rush hour" if rush_start == 7 else "_nolegend_")

    ax1.set_xticks(x)
    ax1.set_xticklabels([f"{h:02d}:00" for h in range(24)], rotation=45, ha="right", fontsize=8)
    ax1.set_xlabel("Hour of day (sim time)")
    ax1.set_ylabel("Number of trips", color="tab:blue")
    ax2.set_ylabel("Unique agents moving", color="tab:orange")
    ax2.set_ylim(bottom=0)
    ax1.set_title(f"Agent mobility by hour - {n_total_agents} agents total")

    lines = [bars, line,
             plt.Rectangle((0, 0), 1, 1, fc="green", alpha=0.15, label="IRL rush hour")]
    ax1.legend(handles=lines, loc="upper left", fontsize=9)
    fig.tight_layout()

    path = out_dir / "mobility_by_hour.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


def plot_trips_per_agent(logs: list[dict], n_total_agents: int, out_dir: Path) -> None:
    trips_per_agent: Counter = Counter(e["agent_id"] for e in logs)
    counts = list(trips_per_agent.values())
    stationary = n_total_agents - len(trips_per_agent)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    ax = axes[0]
    bins = np.arange(0.5, (max(counts) if counts else 1) + 1.5, 1)
    ax.hist(counts, bins=bins, color="tab:blue", edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Trips per agent (moving agents only)")
    ax.set_ylabel("Number of agents")
    ax.set_title(f"Trip count distribution\n"
                 f"({len(trips_per_agent)} moving, {stationary} stationary out of {n_total_agents})")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    axes[1].pie(
        [len(trips_per_agent), stationary],
        labels=[f"Moving\n({len(trips_per_agent)})", f"Stationary\n({stationary})"],
        colors=["tab:blue", "tab:gray"],
        autopct="%1.0f%%",
        startangle=90,
        wedgeprops=dict(edgecolor="white", linewidth=1.5),
    )
    axes[1].set_title("Fraction of agents that moved at all")

    fig.tight_layout()
    path = out_dir / "mobility_per_agent.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


def plot_plan_targets(logs: list[dict], out_dir: Path) -> None:
    target_counts: Counter = Counter(_clean_target(e["plan_target"]) for e in logs)
    target_hour: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    for e in logs:
        target_hour[_clean_target(e["plan_target"])][_parse_sim_hour(e["sim_time"])] += 1

    targets_sorted = [t for t, _ in target_counts.most_common()]
    colors = plt.get_cmap("tab10").colors

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    ax = axes[0]
    y = np.arange(len(targets_sorted))
    ax.barh(y, [target_counts[t] for t in targets_sorted],
            color=[colors[i % len(colors)] for i in range(len(targets_sorted))],
            edgecolor="white", linewidth=0.5)
    ax.set_yticks(y)
    ax.set_yticklabels(targets_sorted)
    ax.invert_yaxis()
    ax.set_xlabel("Number of trips")
    ax.set_title("Movement purpose")

    ax2 = axes[1]
    x = np.arange(24)
    bottom = np.zeros(24)
    for i, target in enumerate(targets_sorted):
        ax2.bar(x, np.array(target_hour[target]), bottom=bottom, label=target,
                color=colors[i % len(colors)], width=0.8)
        bottom += np.array(target_hour[target])
    ax2.set_xticks(x[::2])
    ax2.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)],
                        rotation=45, ha="right", fontsize=8)
    ax2.set_xlabel("Hour of day (sim time)")
    ax2.set_ylabel("Trips")
    ax2.set_title("Movement purpose by hour")
    ax2.legend(fontsize=8, loc="upper right")

    fig.tight_layout()
    path = out_dir / "mobility_plan_targets.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--agents", type=int, default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    logs = load_jsonl(run_dir / "positions" / "position_logs.jsonl")
    n_total = args.agents or len({e["agent_id"] for e in logs})
    out_dir = run_dir / "plots"
    out_dir.mkdir(exist_ok=True)

    print(f"Loaded {len(logs)} position events, {len({e['agent_id'] for e in logs})} unique agents moving")

    plot_trajectories(logs, out_dir)
    plot_distance_distribution(logs, out_dir)
    plot_mobility_by_hour(logs, n_total, out_dir)
    plot_trips_per_agent(logs, n_total, out_dir)
    plot_plan_targets(logs, out_dir)


if __name__ == "__main__":
    main()
