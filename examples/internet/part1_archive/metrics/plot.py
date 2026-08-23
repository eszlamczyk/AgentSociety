"""
Plotting functions for simulation metrics.

Usage:
    from metrics.plot import load_data, plot_wall_time, plot_cumulative_wall_time, ...

    steps_df, agents_df = load_data("metrics/output/1agent")
    fig = plot_wall_time(steps_df)
    fig.savefig("wall_time.png")
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(out_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load steps.csv and agents.csv into DataFrames.

    Returns:
        steps_df:  columns [step, tick, wall_time_s, input_tokens, output_tokens]
        agents_df: columns [step, agent_id, input_tokens, output_tokens]
                   plus derived column [total_tokens]
    """
    out_dir = Path(out_dir)
    steps_df = pd.read_csv(out_dir / "steps.csv")
    agents_df = pd.read_csv(out_dir / "agents.csv")
    agents_df["total_tokens"] = agents_df["input_tokens"] + agents_df["output_tokens"]
    return steps_df, agents_df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_tick(seconds: int) -> str:
    """Convert seconds-into-day to HH:MM string."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    return f"{h:02d}:{m:02d}"


def _add_tick_xaxis(ax: plt.Axes, steps_df: pd.DataFrame) -> None:
    """
    Add a secondary x-axis at the bottom showing sim time (HH:MM).
    The primary axis uses step numbers; the secondary shows tick values.
    """
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.xaxis.set_ticks_position("bottom")
    ax2.xaxis.set_label_position("bottom")
    ax2.spines["bottom"].set_position(("outward", 36))
    ax2.set_xticks(steps_df["step"])
    ax2.set_xticklabels(
        [_fmt_tick(t) for t in steps_df["tick"]], fontsize=7, rotation=45, ha="right"
    )
    ax2.set_xlabel("Sim time (HH:MM)", fontsize=8)


# ---------------------------------------------------------------------------
# Plot 1 — wall time per step
# ---------------------------------------------------------------------------

def plot_wall_time(steps_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """
    Wall-clock seconds per step.
    Primary x-axis: step number.
    Secondary x-axis (below): sim time (HH:MM) at start of each step.
    """
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.subplots_adjust(bottom=0.22)

    ax.plot(steps_df["step"], steps_df["wall_time_s"], marker="o", linewidth=1.5)
    ax.set_xlabel("Step")
    ax.set_ylabel("Wall time (s)")
    ax.set_title(f"Wall-clock time per step  [{run_name}]")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    _add_tick_xaxis(ax, steps_df)
    return fig


# ---------------------------------------------------------------------------
# Plot 2 — cumulative wall time
# ---------------------------------------------------------------------------

def plot_cumulative_wall_time(steps_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """Cumulative wall-clock time across steps."""
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.subplots_adjust(bottom=0.22)

    cumulative = steps_df["wall_time_s"].cumsum()
    ax.plot(steps_df["step"], cumulative, marker="o", linewidth=1.5, color="tab:orange")
    ax.set_xlabel("Step")
    ax.set_ylabel("Cumulative wall time (s)")
    ax.set_title(f"Cumulative wall-clock time  [{run_name}]")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    _add_tick_xaxis(ax, steps_df)
    return fig


# ---------------------------------------------------------------------------
# Plot 3 — tokens per step (input and output as separate lines)
# ---------------------------------------------------------------------------

def plot_tokens_per_step(steps_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """Input and output tokens per step as separate lines."""
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.subplots_adjust(bottom=0.22)

    ax.plot(steps_df["step"], steps_df["input_tokens"],
            marker="o", linewidth=1.5, label="Input tokens")
    ax.plot(steps_df["step"], steps_df["output_tokens"],
            marker="s", linewidth=1.5, label="Output tokens")
    ax.set_xlabel("Step")
    ax.set_ylabel("Tokens")
    ax.set_title(f"Tokens per step  [{run_name}]")
    ax.legend()
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    _add_tick_xaxis(ax, steps_df)
    return fig


# ---------------------------------------------------------------------------
# Plot 4 — cumulative tokens per step
# ---------------------------------------------------------------------------

def plot_cumulative_tokens(steps_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """Cumulative input and output tokens across steps."""
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.subplots_adjust(bottom=0.22)

    ax.plot(steps_df["step"], steps_df["input_tokens"].cumsum(),
            marker="o", linewidth=1.5, label="Input tokens")
    ax.plot(steps_df["step"], steps_df["output_tokens"].cumsum(),
            marker="s", linewidth=1.5, label="Output tokens")
    ax.set_xlabel("Step")
    ax.set_ylabel("Cumulative tokens")
    ax.set_title(f"Cumulative tokens  [{run_name}]")
    ax.legend()
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    _add_tick_xaxis(ax, steps_df)
    return fig


# ---------------------------------------------------------------------------
# Plot 5 — tokens overview: per-step and cumulative as 2 subplots
# ---------------------------------------------------------------------------

def plot_tokens_overview(steps_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """
    Single figure with 2 subplots:
      top:    input and output tokens per step
      bottom: cumulative input and output tokens
    Both share the same x-axis (step + sim-time secondary axis).
    """
    fig, (ax_per, ax_cum) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    fig.subplots_adjust(bottom=0.18, hspace=0.35)

    # --- top: per step ---
    ax_per.plot(steps_df["step"], steps_df["input_tokens"],
                marker="o", linewidth=1.5, label="Input")
    ax_per.plot(steps_df["step"], steps_df["output_tokens"],
                marker="s", linewidth=1.5, label="Output")
    ax_per.set_ylabel("Tokens")
    ax_per.set_title(f"Tokens per step  [{run_name}]")
    ax_per.legend()

    # --- bottom: cumulative ---
    ax_cum.plot(steps_df["step"], steps_df["input_tokens"].cumsum(),
                marker="o", linewidth=1.5, label="Input (cumulative)")
    ax_cum.plot(steps_df["step"], steps_df["output_tokens"].cumsum(),
                marker="s", linewidth=1.5, label="Output (cumulative)")
    ax_cum.set_xlabel("Step")
    ax_cum.set_ylabel("Cumulative tokens")
    ax_cum.set_title(f"Cumulative tokens  [{run_name}]")
    ax_cum.legend()
    ax_cum.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    _add_tick_xaxis(ax_cum, steps_df)
    return fig


# ---------------------------------------------------------------------------
# Plot 6 — tokens per second (throughput)
# ---------------------------------------------------------------------------

def plot_tokens_per_second(steps_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """Total tokens (input + output) per wall-clock second, per step."""
    fig, ax = plt.subplots(figsize=(10, 4))
    fig.subplots_adjust(bottom=0.22)

    total = steps_df["input_tokens"] + steps_df["output_tokens"]
    tps = total / steps_df["wall_time_s"]

    ax.plot(steps_df["step"], tps, marker="o", linewidth=1.5, color="tab:green")
    ax.set_xlabel("Step")
    ax.set_ylabel("Tokens / second")
    ax.set_title(f"Tokens per second (throughput)  [{run_name}]")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    _add_tick_xaxis(ax, steps_df)
    return fig


# ---------------------------------------------------------------------------
# Plot 7 — total tokens per agent per step (one line per agent)
# ---------------------------------------------------------------------------

def plot_tokens_per_agent(agents_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """
    Total tokens (input + output) per step for each agent.
    One line per agent_id.
    """
    fig, ax = plt.subplots(figsize=(10, 5))

    for agent_id, group in agents_df.groupby("agent_id"):
        ax.plot(group["step"], group["total_tokens"],
                marker="o", linewidth=1.5, label=f"Agent {agent_id}")

    ax.set_xlabel("Step")
    ax.set_ylabel("Total tokens")
    ax.set_title(f"Total tokens per agent per step  [{run_name}]")
    ax.legend(fontsize=8, ncol=max(1, len(agents_df["agent_id"].unique()) // 10))
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    return fig


# ---------------------------------------------------------------------------
# Plot 8 — input vs output per agent per step (2 subplots)
# ---------------------------------------------------------------------------

def _sim_time_labels(steps_df: pd.DataFrame) -> list[str]:
    """HH:MM labels for each step's tick value."""
    return [_fmt_tick(t) for t in steps_df["tick"]]


# ---------------------------------------------------------------------------
# Comparison plots — multiple runs on one figure
# ---------------------------------------------------------------------------

def plot_compare_wall_time(runs: dict[str, tuple[pd.DataFrame, int]]) -> plt.Figure:
    """
    Plot 1: total wall time per step, one line per run.

    Args:
        runs: {label: (steps_df, n_agents)}
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    fig.subplots_adjust(bottom=0.18)

    for label, (df, _) in runs.items():
        ax.plot(df["tick"] / 3600, df["wall_time_s"], marker="o", linewidth=1.5, label=label)

    ax.set_xlabel("Sim time (hours into day)")
    ax.set_ylabel("Wall time per step (s)")
    ax.set_title("Total wall time per step — all runs")
    ax.legend()
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.1f}h"))
    return fig


def plot_compare_wall_time_per_agent(runs: dict[str, tuple[pd.DataFrame, int]]) -> plt.Figure:
    """
    Plot 2: wall time per agent per step, one line per run.

    Args:
        runs: {label: (steps_df, n_agents)}
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    fig.subplots_adjust(bottom=0.18)

    for label, (df, n) in runs.items():
        ax.plot(df["tick"] / 3600, df["wall_time_s"] / n, marker="o", linewidth=1.5, label=label)

    ax.set_xlabel("Sim time (hours into day)")
    ax.set_ylabel("Wall time per agent per step (s)")
    ax.set_title("Wall time per agent per step — all runs")
    ax.legend()
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.1f}h"))
    return fig


def plot_compare_tokens_per_agent(runs: dict[str, tuple[pd.DataFrame, int]]) -> plt.Figure:
    """
    Plot 3: (input + output) tokens per agent per step, one line per run.

    Args:
        runs: {label: (steps_df, n_agents)}
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    fig.subplots_adjust(bottom=0.18)

    for label, (df, n) in runs.items():
        total_tok = df["input_tokens"] + df["output_tokens"]
        ax.plot(df["tick"] / 3600, total_tok / n, marker="o", linewidth=1.5, label=label)

    ax.set_xlabel("Sim time (hours into day)")
    ax.set_ylabel("Tokens per agent per step")
    ax.set_title("Total tokens per agent per step — all runs")
    ax.legend()
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.1f}h"))
    return fig


def plot_compare_tokens_per_second(runs: dict[str, tuple[pd.DataFrame, int]]) -> plt.Figure:
    """
    Plot 4: total tokens/s throughput per step, one line per run.

    Args:
        runs: {label: (steps_df, n_agents)}
    """
    fig, ax = plt.subplots(figsize=(11, 5))
    fig.subplots_adjust(bottom=0.18)

    for label, (df, _) in runs.items():
        tps = (df["input_tokens"] + df["output_tokens"]) / df["wall_time_s"]
        ax.plot(df["tick"] / 3600, tps, marker="o", linewidth=1.5, label=label)

    ax.set_xlabel("Sim time (hours into day)")
    ax.set_ylabel("Tokens / second")
    ax.set_title("PLGrid throughput (tokens/s) — all runs")
    ax.legend()
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{x:.1f}h"))
    return fig


def plot_agent_input_output(agents_df: pd.DataFrame, run_name: str = "") -> plt.Figure:
    """
    Two subplots side by side:
      left:  input tokens per step, one line per agent
      right: output tokens per step, one line per agent
    """
    agent_ids = sorted(agents_df["agent_id"].dropna().unique())
    n_agents = len(agent_ids)
    legend_cols = max(1, n_agents // 10)

    fig, (ax_in, ax_out) = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    fig.suptitle(f"Input vs Output tokens per agent per step  [{run_name}]")

    for agent_id in agent_ids:
        group = agents_df[agents_df["agent_id"] == agent_id]
        label = f"Agent {agent_id}"
        ax_in.plot(group["step"], group["input_tokens"],
                   marker="o", linewidth=1.2, label=label)
        ax_out.plot(group["step"], group["output_tokens"],
                    marker="s", linewidth=1.2, label=label)

    ax_in.set_xlabel("Step")
    ax_in.set_ylabel("Input tokens")
    ax_in.set_title("Input tokens")
    ax_in.legend(fontsize=8, ncol=legend_cols)
    ax_in.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    ax_out.set_xlabel("Step")
    ax_out.set_ylabel("Output tokens")
    ax_out.set_title("Output tokens")
    ax_out.legend(fontsize=8, ncol=legend_cols)
    ax_out.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))

    fig.tight_layout()
    return fig
