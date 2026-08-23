"""
Generate comparison plots across multiple runs.

Usage:
    python metrics/compare.py
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).parent))
from plot import load_data, plot_compare_wall_time, plot_compare_wall_time_per_agent, plot_compare_tokens_per_agent, plot_compare_tokens_per_second

RUNS = {
    "1 agent":    ("metrics/output/1agent",                   1),
    "10 agents":  ("metrics/output/10agent1Hour",             10),
    "100 agents": ("metrics/output/100agent1Hour",            100),
    "1000 agents":("metrics/output/1000agent_ratelimit_test", 1000),
    "2000 agents":("metrics/output/2000agent_throughput_test",2000),
}

OUT_DIR = Path("metrics/output/comparison_plots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Load data — keep only the first 12 steps (1 hour) for each run
runs = {}
for label, (path, n) in RUNS.items():
    steps_df, _ = load_data(path)
    runs[label] = (steps_df.iloc[:12].copy(), n)

plots = [
    ("01_wall_time_total",      plot_compare_wall_time(runs)),
    ("02_wall_time_per_agent",  plot_compare_wall_time_per_agent(runs)),
    ("03_tokens_per_agent",     plot_compare_tokens_per_agent(runs)),
    ("04_tokens_per_second",    plot_compare_tokens_per_second(runs)),
]

for name, fig in plots:
    path = OUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)
