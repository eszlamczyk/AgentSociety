"""
Website visit statistics from device_usage_logs.jsonl.
Generates an interactive HTML dashboard with charts.
"""

import os
import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots

LOG_FILE = os.path.join(os.path.dirname(__file__), "internet_logs", "device_usage_logs.jsonl")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "website_stats.html")


def load_data(log_file: str) -> pl.DataFrame:
    df = pl.read_ndjson(log_file)
    return df.filter(pl.col("website").is_not_null())


def render(df: pl.DataFrame, output_file: str):
    # --- Top 20 most visited sites ---
    top_sites = (
        df.group_by("website")
        .len()
        .rename({"len": "visits"})
        .sort("visits", descending=True)
        .head(20)
    )

    # --- Visits by action_type ---
    by_action = (
        df.group_by("action_type")
        .len()
        .rename({"len": "visits"})
        .sort("visits", descending=True)
    )

    # --- Top 10 sites per action_type ---
    top_per_action = (
        df.group_by(["action_type", "website"])
        .len()
        .rename({"len": "visits"})
        .sort("visits", descending=True)
        .group_by("action_type")
        .head(5)
        .sort(["action_type", "visits"], descending=[False, True])
    )

    # --- Most active agents (by visit count) ---
    top_agents = (
        df.group_by(["agent_id", "agent_name"])
        .len()
        .rename({"len": "visits"})
        .sort("visits", descending=True)
        .head(20)
    )

    # --- Visits by device type ---
    by_device = (
        df.group_by("device_type")
        .len()
        .rename({"len": "visits"})
        .sort("visits", descending=True)
    )

    # --- Unique sites per agent (breadth of browsing) ---
    unique_per_agent = (
        df.group_by("agent_id")
        .agg(pl.col("website").n_unique().alias("unique_sites"))
        .sort("unique_sites", descending=True)
        .head(20)
    )

    # ---- Build dashboard ----
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=[
            "Top 20 Most Visited Websites",
            "Visits by Action Type",
            "Top 5 Sites per Action Type",
            "Most Active Agents",
            "Visits by Device Type",
            "Unique Sites per Agent (top 20)",
        ],
        vertical_spacing=0.12,
        horizontal_spacing=0.08,
    )

    # 1. Top 20 sites — horizontal bar
    fig.add_trace(go.Bar(
        x=top_sites["visits"].to_list(),
        y=top_sites["website"].to_list(),
        orientation="h",
        marker_color="#2980b9",
        name="Visits",
        showlegend=False,
    ), row=1, col=1)

    # 2. Visits by action type — pie
    fig.add_trace(go.Pie(
        labels=by_action["action_type"].to_list(),
        values=by_action["visits"].to_list(),
        hole=0.4,
        name="Action types",
        showlegend=True,
    ), row=1, col=2)

    # 3. Top 5 sites per action type — grouped bar
    action_types = top_per_action["action_type"].unique().to_list()
    colors = ["#2980b9", "#e74c3c", "#27ae60", "#f39c12", "#8e44ad", "#16a085"]
    for i, at in enumerate(sorted(action_types)):
        subset = top_per_action.filter(pl.col("action_type") == at)
        fig.add_trace(go.Bar(
            name=at,
            x=subset["website"].to_list(),
            y=subset["visits"].to_list(),
            marker_color=colors[i % len(colors)],
        ), row=2, col=1)

    # 4. Most active agents — horizontal bar
    fig.add_trace(go.Bar(
        x=top_agents["visits"].to_list(),
        y=top_agents["agent_name"].to_list(),
        orientation="h",
        marker_color="#e74c3c",
        name="Agent visits",
        showlegend=False,
    ), row=2, col=2)

    # 5. Visits by device type — bar
    fig.add_trace(go.Bar(
        x=by_device["device_type"].to_list(),
        y=by_device["visits"].to_list(),
        marker_color="#27ae60",
        name="Device visits",
        showlegend=False,
    ), row=3, col=1)

    # 6. Unique sites per agent — bar
    fig.add_trace(go.Bar(
        x=[str(a) for a in unique_per_agent["agent_id"].to_list()],
        y=unique_per_agent["unique_sites"].to_list(),
        marker_color="#8e44ad",
        name="Unique sites",
        showlegend=False,
    ), row=3, col=2)

    fig.update_layout(
        title=f"Website Visit Statistics — {len(df):,} total visits, {df['website'].n_unique()} unique sites",
        height=1400,
        barmode="group",
        plot_bgcolor="white",
        paper_bgcolor="#f8f9fa",
    )
    fig.update_xaxes(showgrid=True, gridcolor="#eeeeee")
    fig.update_yaxes(showgrid=True, gridcolor="#eeeeee")

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    fig.write_html(output_file)
    print(f"Saved: {output_file}")


def print_summary(df: pl.DataFrame):
    print(f"\nTotal visits:    {len(df):,}")
    print(f"Unique websites: {df['website'].n_unique()}")
    print(f"Unique agents:   {df['agent_id'].n_unique()}")
    print(f"\nTop 10 sites:")
    top = (
        df.group_by("website").len().rename({"len": "visits"})
        .sort("visits", descending=True).head(10)
    )
    for row in top.to_dicts():
        print(f"  {row['visits']:4d}x  {row['website']}")


def main():
    print("Loading data...")
    df = load_data(LOG_FILE)
    print_summary(df)
    print("\nGenerating dashboard...")
    render(df, OUTPUT_FILE)


if __name__ == "__main__":
    main()
