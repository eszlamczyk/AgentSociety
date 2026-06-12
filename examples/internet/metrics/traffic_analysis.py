"""
Traffic and IP analysis for internet simulation runs.

Plots generated:
  ip_per_agent.png            - unique IP addresses per agent (home vs antenna)
  top_websites_per_type.png   - top websites per action type (faceted bars)
  traffic_per_agent.png       - traffic type breakdown per agent (stacked bar)
  action_descriptions.png     - sample action_description text frequency per type

Usage:
    python metrics/traffic_analysis.py run_logs/100agent_fullday
"""

import argparse
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
# Data loading
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(l) for l in f if l.strip()]


# ---------------------------------------------------------------------------
# Plot 1 — unique IP addresses per agent
# ---------------------------------------------------------------------------

def plot_ip_per_agent(device_logs: list[dict], conn_logs: list[dict], out_dir: Path) -> None:
    # Collect IPs per agent from both log sources
    home_ips: dict[int, set] = defaultdict(set)
    antenna_ips: dict[int, set] = defaultdict(set)

    for e in device_logs:
        ip = e.get("ip_address")
        if not ip:
            continue
        aid = e["agent_id"]
        if ip.startswith("172."):
            home_ips[aid].add(ip)
        else:
            antenna_ips[aid].add(ip)

    for e in conn_logs:
        if e.get("action") != "connect":
            continue
        ip = e.get("ip_address")
        if not ip:
            continue
        aid = e["agent_id"]
        if ip.startswith("172."):
            home_ips[aid].add(ip)
        else:
            antenna_ips[aid].add(ip)

    all_agents = sorted(set(home_ips) | set(antenna_ips))
    home_counts   = np.array([len(home_ips.get(a, set()))    for a in all_agents])
    antenna_counts = np.array([len(antenna_ips.get(a, set())) for a in all_agents])
    total = home_counts + antenna_counts

    # all_agents is already sorted by agent_id (sorted() above)
    agents_sorted = all_agents
    home_s    = home_counts
    antenna_s = antenna_counts
    total_s   = total

    fig, axes = plt.subplots(2, 1, figsize=(16, 9))

    # Top: stacked bar per agent
    ax = axes[0]
    x = np.arange(len(agents_sorted))
    ax.bar(x, home_s,    label="Home WiFi (172.x)", color="tab:blue",   width=0.8)
    ax.bar(x, antenna_s, label="Antenna (10.x)",    color="tab:orange", width=0.8, bottom=home_s)
    ax.set_xticks(x[::5])
    ax.set_xticklabels([f"A{agents_sorted[i]}" for i in range(0, len(agents_sorted), 5)],
                       rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("Unique IP addresses")
    ax.set_title("Unique IP addresses per agent (sorted by agent ID)")
    ax.legend()
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    # Bottom: histogram of total IP count distribution
    ax2 = axes[1]
    max_ips = int(total_s.max()) if len(total_s) else 1
    bins = np.arange(0.5, max_ips + 1.5, 1)
    ax2.hist(total_s, bins=bins, color="tab:purple", edgecolor="white", linewidth=0.5)
    ax2.set_xlabel("Number of unique IPs per agent")
    ax2.set_ylabel("Number of agents")
    ax2.set_title("Distribution: how many unique IPs did each agent have?")
    ax2.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    # Stats annotation
    stats = (
        f"min={total_s.min()}  max={total_s.max()}  "
        f"mean={total_s.mean():.1f}  median={np.median(total_s):.1f}"
    )
    ax2.text(0.98, 0.95, stats, transform=ax2.transAxes,
             ha="right", va="top", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.7))

    fig.tight_layout(pad=2.0)
    path = out_dir / "ip_per_agent.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot 2 — top websites per action type
# ---------------------------------------------------------------------------

def plot_top_websites(device_logs: list[dict], out_dir: Path, top_n: int = 10) -> None:
    # Group website counts by action type
    type_site_counts: dict[str, Counter] = defaultdict(Counter)
    for e in device_logs:
        site = e.get("website") or ""
        if site:
            type_site_counts[e["action_type"]][site] += 1

    action_types = sorted(type_site_counts.keys())
    n = len(action_types)
    ncols = 3
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows))
    axes_flat = axes.flatten() if n > 1 else [axes]

    colors = plt.get_cmap("tab10").colors

    for idx, atype in enumerate(action_types):
        ax = axes_flat[idx]
        top = type_site_counts[atype].most_common(top_n)
        sites, counts = zip(*top) if top else ([], [])
        y = np.arange(len(sites))
        ax.barh(y, counts, color=colors[idx % len(colors)], edgecolor="white", linewidth=0.5)
        ax.set_yticks(y)
        ax.set_yticklabels(sites, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Actions")
        ax.set_title(f"{atype}  (total: {sum(type_site_counts[atype].values())})")
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    # Hide unused subplots
    for idx in range(len(action_types), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle(f"Top {top_n} websites per traffic type", fontsize=13, y=1.01)
    fig.tight_layout()
    path = out_dir / "top_websites_per_type.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot 3 — traffic type breakdown per agent (stacked bar)
# ---------------------------------------------------------------------------

def plot_traffic_per_agent(device_logs: list[dict], out_dir: Path) -> None:
    action_types = sorted({e["action_type"] for e in device_logs})
    agent_type_counts: dict[int, Counter] = defaultdict(Counter)
    for e in device_logs:
        agent_type_counts[e["agent_id"]][e["action_type"]] += 1

    agents = sorted(agent_type_counts.keys())
    # Sort agents by total actions
    totals = [sum(agent_type_counts[a].values()) for a in agents]
    order = np.argsort(-np.array(totals))
    agents_sorted = [agents[i] for i in order]

    colors = plt.get_cmap("tab10").colors
    x = np.arange(len(agents_sorted))

    fig, ax = plt.subplots(figsize=(16, 5))
    bottom = np.zeros(len(agents_sorted))
    for ci, atype in enumerate(action_types):
        vals = np.array([agent_type_counts[a].get(atype, 0) for a in agents_sorted], dtype=float)
        ax.bar(x, vals, bottom=bottom, label=atype, color=colors[ci % len(colors)], width=0.8)
        bottom += vals

    ax.set_xticks(x[::5])
    ax.set_xticklabels([f"A{agents_sorted[i]}" for i in range(0, len(agents_sorted), 5)],
                       rotation=60, ha="right", fontsize=7)
    ax.set_ylabel("Number of actions")
    ax.set_title("Traffic type breakdown per agent (sorted by total activity)")
    ax.legend(loc="upper right", ncol=3, fontsize=8)
    fig.tight_layout()

    path = out_dir / "traffic_per_agent.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plot 4 — action description analysis (top keywords per type)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "and", "the", "to", "a", "an", "in", "of", "for", "on", "at", "with",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "check", "use", "using", "via", "from", "or", "by", "this", "that",
    "their", "some", "all", "new", "my", "i", "me", "your", "up", "out",
}

def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def plot_action_descriptions(device_logs: list[dict], out_dir: Path, top_n: int = 15) -> None:
    type_word_counts: dict[str, Counter] = defaultdict(Counter)
    for e in device_logs:
        desc = e.get("action_description") or ""
        atype = e["action_type"]
        for w in _tokenize(desc):
            type_word_counts[atype][w] += 1

    action_types = sorted(type_word_counts.keys())
    n = len(action_types)
    ncols = 3
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows))
    axes_flat = axes.flatten() if n > 1 else [axes]
    colors = plt.get_cmap("tab10").colors

    for idx, atype in enumerate(action_types):
        ax = axes_flat[idx]
        top = type_word_counts[atype].most_common(top_n)
        if not top:
            ax.set_visible(False)
            continue
        words, counts = zip(*top)
        y = np.arange(len(words))
        ax.barh(y, counts, color=colors[idx % len(colors)], edgecolor="white", linewidth=0.4)
        ax.set_yticks(y)
        ax.set_yticklabels(words, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("Word count")
        ax.set_title(f'"{atype}" descriptions — top keywords')
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    for idx in range(len(action_types), len(axes_flat)):
        axes_flat[idx].set_visible(False)

    fig.suptitle("Most common keywords in agent action descriptions per traffic type",
                 fontsize=12, y=1.01)
    fig.tight_layout()
    path = out_dir / "action_description_keywords.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", help="Run directory (contains internet/ subdir)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    device_log_path = run_dir / "internet" / "device_usage_logs.jsonl"
    conn_log_path   = run_dir / "internet" / "antenna_device_connections.jsonl"
    out_dir = run_dir / "plots"
    out_dir.mkdir(exist_ok=True)

    device_logs = load_jsonl(device_log_path)
    conn_logs   = load_jsonl(conn_log_path) if conn_log_path.exists() else []

    print(f"Loaded {len(device_logs)} device actions, {len(conn_logs)} connection events")

    plot_ip_per_agent(device_logs, conn_logs, out_dir)
    plot_top_websites(device_logs, out_dir)
    plot_traffic_per_agent(device_logs, out_dir)
    plot_action_descriptions(device_logs, out_dir)


if __name__ == "__main__":
    main()
