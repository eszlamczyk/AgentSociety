"""
Render all plots from a metrics output directory.

Usage:
    python metrics/render.py metrics/output/1agent
    python metrics/render.py metrics/output/1agent --show   # open windows
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless by default
import matplotlib.pyplot as plt

from plot import (
    load_data,
    plot_wall_time,
    plot_cumulative_wall_time,
    plot_tokens_per_step,
    plot_cumulative_tokens,
    plot_tokens_overview,
    plot_tokens_per_second,
    plot_tokens_per_agent,
    plot_agent_input_output,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", help="Directory containing steps.csv and agents.csv")
    parser.add_argument("--show", action="store_true", help="Show interactive windows")
    args = parser.parse_args()

    if args.show:
        matplotlib.use("TkAgg")

    data_dir = Path(args.data_dir)
    out_dir = data_dir / "plots"
    out_dir.mkdir(exist_ok=True)

    steps_df, agents_df = load_data(data_dir)
    run_name = data_dir.name

    plots = [
        ("01_wall_time_per_step",        plot_wall_time(steps_df, run_name)),
        ("02_cumulative_wall_time",       plot_cumulative_wall_time(steps_df, run_name)),
        ("03_tokens_per_step",            plot_tokens_per_step(steps_df, run_name)),
        ("04_cumulative_tokens",          plot_cumulative_tokens(steps_df, run_name)),
        ("05_tokens_overview",            plot_tokens_overview(steps_df, run_name)),
        ("06_tokens_per_second",          plot_tokens_per_second(steps_df, run_name)),
        ("07_tokens_per_agent_per_step",  plot_tokens_per_agent(agents_df, run_name)),
        ("08_agent_input_vs_output",      plot_agent_input_output(agents_df, run_name)),
    ]

    for name, fig in plots:
        path = out_dir / f"{name}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        print(f"Saved {path}")
        if args.show:
            plt.show()
        plt.close(fig)


if __name__ == "__main__":
    main()
