"""
Graph visualization: Agent ID <-> IP Address
Uses polars for data loading, igraph for graph construction/layout,
and plotly (Scattergl/WebGL) for interactive HTML output.

Supports two network types:
  - antenna   (10.x.x.x)   → red/orange nodes, grouped by antenna_id
  - home_wifi (192.168.x.x) → green nodes, grouped by home_aoi_id
"""

import os
import polars as pl
import igraph as ig
import plotly.graph_objects as go

LOG_FILE = os.path.join(os.path.dirname(__file__), "internet_logs", "antenna_device_connections.jsonl")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "graph_interactive.html")


def load_edges(log_file: str) -> pl.DataFrame:
    df = pl.read_ndjson(log_file)
    df = df.filter(pl.col("action") == "connect")

    # Unify antenna_id / home_aoi_id into a single "group_id" column for coloring
    if "network_type" not in df.columns:
        # Old logs without network_type — treat all as antenna
        df = df.with_columns(pl.lit("antenna").alias("network_type"))
    if "home_aoi_id" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Int64).alias("home_aoi_id"))
    if "antenna_id" not in df.columns:
        df = df.with_columns(pl.lit(None).cast(pl.Int64).alias("antenna_id"))

    df = df.with_columns(
        pl.when(pl.col("network_type") == "home_wifi")
        .then(pl.col("home_aoi_id").cast(pl.Int64))
        .otherwise(pl.col("antenna_id").cast(pl.Int64))
        .alias("group_id")
    )

    edges = (
        df.group_by(["agent_id", "agent_name", "ip_address", "device_type", "network_type", "group_id"])
        .len()
        .rename({"len": "weight"})
    )
    return edges


def build_graph(edges: pl.DataFrame) -> ig.Graph:
    agent_ids = edges["agent_id"].unique().to_list()
    ip_addresses = edges["ip_address"].unique().to_list()

    agent_names = {
        row["agent_id"]: row["agent_name"]
        for row in edges.select(["agent_id", "agent_name"]).unique().to_dicts()
    }

    # Per-IP metadata (network_type + group_id)
    ip_meta = {
        row["ip_address"]: {"network_type": row["network_type"], "group_id": row["group_id"]}
        for row in edges.select(["ip_address", "network_type", "group_id"]).unique().to_dicts()
    }

    agent_idx = {aid: i for i, aid in enumerate(agent_ids)}
    ip_idx = {ip: len(agent_ids) + i for i, ip in enumerate(ip_addresses)}

    n_agents = len(agent_ids)
    n_ips = len(ip_addresses)

    g = ig.Graph(n=n_agents + n_ips, directed=False)

    g.vs["node_type"] = ["agent"] * n_agents + ["ip"] * n_ips
    g.vs["label"] = (
        [agent_names.get(aid, f"Agent_{aid}") for aid in agent_ids]
        + list(ip_addresses)
    )
    g.vs["agent_id"] = agent_ids + [None] * n_ips
    g.vs["network_type"] = [None] * n_agents + [ip_meta[ip]["network_type"] for ip in ip_addresses]
    g.vs["group_id"] = [None] * n_agents + [ip_meta[ip]["group_id"] for ip in ip_addresses]

    edge_list, weights, device_types = [], [], []
    for row in edges.to_dicts():
        edge_list.append((agent_idx[row["agent_id"]], ip_idx[row["ip_address"]]))
        weights.append(row["weight"])
        device_types.append(row["device_type"])

    g.add_edges(edge_list)
    g.es["weight"] = weights
    g.es["device_type"] = device_types

    return g


def antenna_color(group_id, all_group_ids: list) -> str:
    """Map antenna group_id to red/orange hue."""
    if group_id is None:
        return "#e74c3c"
    unique_sorted = sorted(set(g for g in all_group_ids if g is not None))
    idx = unique_sorted.index(group_id) if group_id in unique_sorted else 0
    ratio = idx / max(1, len(unique_sorted) - 1)
    g_val = int(80 + ratio * 100)
    b = int(50 + ratio * 50)
    return f"rgb(255,{g_val},{b})"


def home_color(group_id, all_group_ids: list) -> str:
    """Map home_aoi group_id to green hue."""
    if group_id is None:
        return "#27ae60"
    unique_sorted = sorted(set(g for g in all_group_ids if g is not None))
    idx = unique_sorted.index(group_id) if group_id in unique_sorted else 0
    ratio = idx / max(1, len(unique_sorted) - 1)
    r = int(30 + ratio * 60)
    g_val = int(150 + ratio * 80)
    return f"rgb({r},{g_val},80)"


def render_plotly(g: ig.Graph, output_file: str):
    print("Computing layout (Fruchterman-Reingold)...")
    import random
    random.seed(42)
    layout = g.layout_fruchterman_reingold(weights=g.es["weight"])
    coords = layout.coords

    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]

    # --- Edge trace ---
    edge_x, edge_y = [], []
    for edge in g.es:
        x0, y0 = coords[edge.source]
        x1, y1 = coords[edge.target]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scattergl(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=0.5, color="#aaaaaa"),
        hoverinfo="none",
        name="Connection",
    )

    # --- Agent nodes ---
    agent_vs = [v for v in g.vs if v["node_type"] == "agent"]
    agent_trace = go.Scattergl(
        x=[xs[v.index] for v in agent_vs],
        y=[ys[v.index] for v in agent_vs],
        mode="markers",
        marker=dict(size=10, color="#2980b9", line=dict(width=1, color="white")),
        text=[v["label"] for v in agent_vs],
        textposition="top center",
        textfont=dict(size=9, color="#2980b9"),
        customdata=[v["agent_id"] for v in agent_vs],
        hovertemplate="<b>%{text}</b><br>Agent ID: %{customdata}<extra></extra>",
        name="Agent",
    )

    # --- Antenna IP nodes (10.x.x.x) ---
    antenna_vs = [v for v in g.vs if v["node_type"] == "ip" and v["network_type"] == "antenna"]
    antenna_group_ids = [v["group_id"] for v in antenna_vs]
    antenna_colors = [antenna_color(v["group_id"], antenna_group_ids) for v in antenna_vs]
    antenna_trace = go.Scattergl(
        x=[xs[v.index] for v in antenna_vs],
        y=[ys[v.index] for v in antenna_vs],
        mode="markers",
        marker=dict(size=6, color=antenna_colors, line=dict(width=0.5, color="white")),
        text=[v["label"] for v in antenna_vs],
        textposition="bottom center",
        textfont=dict(size=8, color="#c0392b"),
        customdata=[v["group_id"] for v in antenna_vs],
        hovertemplate="<b>IP: %{text}</b><br>Antenna ID: %{customdata}<extra></extra>",
        name="IP (antenna)",
    )

    # --- Home WiFi IP nodes (192.168.x.x) ---
    home_vs = [v for v in g.vs if v["node_type"] == "ip" and v["network_type"] == "home_wifi"]
    home_group_ids = [v["group_id"] for v in home_vs]
    home_colors = [home_color(v["group_id"], home_group_ids) for v in home_vs]
    home_trace = go.Scattergl(
        x=[xs[v.index] for v in home_vs],
        y=[ys[v.index] for v in home_vs],
        mode="markers",
        marker=dict(size=7, color=home_colors, symbol="diamond", line=dict(width=0.5, color="white")),
        text=[v["label"] for v in home_vs],
        textposition="bottom center",
        textfont=dict(size=8, color="#1e8449"),
        customdata=[v["group_id"] for v in home_vs],
        hovertemplate="<b>IP: %{text}</b><br>Home AOI: %{customdata}<extra></extra>",
        name="IP (home WiFi)",
    )

    fig = go.Figure(
        data=[edge_trace, agent_trace, antenna_trace, home_trace],
        layout=go.Layout(
            title="Agent ID ↔ IP Address Graph",
            showlegend=True,
            hovermode="closest",
            dragmode="pan",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor="white",
            legend=dict(itemsizing="constant"),
        ),
    )

    # JavaScript: show labels only when zoomed in enough
    post_script = """
    var gd = document.querySelector('.js-plotly-plot');
    var initialXRange = null;

    gd.on('plotly_afterplot', function() {
        if (initialXRange === null) {
            initialXRange = Math.abs(gd.layout.xaxis.range[1] - gd.layout.xaxis.range[0]);
        }
    });

    gd.on('plotly_relayout', function(ed) {
        if (initialXRange === null) return;
        var xr = gd.layout.xaxis.range;
        if (!xr) return;
        var currentWidth = Math.abs(xr[1] - xr[0]);
        var showLabels = currentWidth < initialXRange * 0.35;
        var newMode = showLabels ? 'markers+text' : 'markers';
        // traces 1 = agents, 2 = antenna IPs, 3 = home IPs
        Plotly.restyle(gd, {mode: newMode}, [1, 2, 3]);
    });
    """

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    fig.write_html(output_file, post_script=post_script)
    print(f"Saved: {output_file}")


def main():
    print("Loading data...")
    edges = load_edges(LOG_FILE)
    n_antenna = edges.filter(pl.col("network_type") == "antenna")["ip_address"].n_unique()
    n_home = edges.filter(pl.col("network_type") == "home_wifi")["ip_address"].n_unique()
    print(f"  {len(edges)} unique agent-IP pairs, "
          f"{edges['agent_id'].n_unique()} agents, "
          f"{edges['ip_address'].n_unique()} IPs "
          f"({n_antenna} antenna, {n_home} home WiFi)")

    print("Building graph...")
    g = build_graph(edges)
    print(f"  {g.vcount()} nodes, {g.ecount()} edges")

    render_plotly(g, OUTPUT_FILE)


if __name__ == "__main__":
    main()
