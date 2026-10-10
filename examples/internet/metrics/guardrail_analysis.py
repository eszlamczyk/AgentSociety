"""
Guardrail / robustness plots for a run.

Reads run_dir/metrics_output/guardrails.csv (long format: step, guardrail,
count — written by metrics/collect.py from utils/guardrails.py counters) and
run_dir/metrics_output/steps.csv, and writes:

  guardrail_firings_by_step.png  - stacked bars: how many times each guardrail
                                   fired per simulation step (one hour per
                                   12 steps at 5 sim-min/step)
  guardrail_totals.png           - horizontal bars: total firings per guardrail
                                   over the whole run

The point of these plots is to show how often the weak model (or the
simulator) had to be rescued — a run that "worked" with 400 silent fallbacks
is a different result from one with 4.

Usage:
    python metrics/guardrail_analysis.py logs/2026-10-11
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# Fixed categorical order: the same guardrail always gets the same colour in
# every run's plot, so before/after figures can be compared side by side.
# Colours are the dataviz default palette slots 1-8 (CVD-validated); names
# beyond the first 8 fold into a single "other" series.
_SERIES_COLORS = [
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#6250d6", "#e34948",
]
_OTHER_COLOR = "#9a9892"
_MAX_NAMED_SERIES = 8

# Severity order for colour assignment (worst first). Names not listed are
# appended alphabetically after these.
_PRIORITY = [
    "agent_tick_exception",
    "satisfaction_eval_exhausted",
    "get_person_rpc_failed",
    "satisfaction_eval_retry",
    "vendored_plan_detail_parse",
    "vendored_plan_guidance_parse",
    "mobility_place_analysis_parse_fallback",
    "vendored_mobility_level1_random",
    "vendored_mobility_level2_random",
    "vendored_mobility_radius_default",
    "other_duration_random",
    "website_selection_fallback",
]


def _load_guardrails(path: Path) -> dict[str, dict[int, int]]:
    """{guardrail: {step: count}}"""
    out: dict[str, dict[int, int]] = defaultdict(dict)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out[row["guardrail"]][int(row["step"])] = int(row["count"])
    return out


def _n_steps(steps_csv: Path, fallback: int) -> int:
    if not steps_csv.exists():
        return fallback
    with open(steps_csv, newline="") as f:
        n = sum(1 for _ in csv.DictReader(f))
    return max(n, fallback)


def _ordered_names(names: set[str]) -> list[str]:
    ranked = [n for n in _PRIORITY if n in names]
    ranked += sorted(n for n in names if n not in _PRIORITY)
    return ranked


def plot_by_step(data: dict[str, dict[int, int]], n_steps: int, out_dir: Path) -> None:
    names = _ordered_names(set(data))
    named = names[:_MAX_NAMED_SERIES]
    folded = names[_MAX_NAMED_SERIES:]

    series: list[tuple[str, np.ndarray, str]] = []
    for i, name in enumerate(named):
        y = np.zeros(n_steps)
        for step, c in data[name].items():
            if step < n_steps:
                y[step] = c
        series.append((name, y, _SERIES_COLORS[i]))
    if folded:
        y = np.zeros(n_steps)
        for name in folded:
            for step, c in data[name].items():
                if step < n_steps:
                    y[step] += c
        series.append((f"other ({len(folded)} guardrails)", y, _OTHER_COLOR))

    x = np.arange(n_steps)
    fig, ax = plt.subplots(figsize=(14, 5))
    bottom = np.zeros(n_steps)
    for name, y, color in series:
        ax.bar(x, y, bottom=bottom, width=0.9, color=color, label=name,
               edgecolor="white", linewidth=0.5)
        bottom += y

    ax.set_xlabel("simulation step (12 steps = 1 sim hour)")
    ax.set_ylabel("guardrail firings")
    ax.set_title("Guardrail firings per step (fallbacks that kept the run alive)")
    ax.yaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#e5e4e0", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=False, fontsize=8)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "guardrail_firings_by_step.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_totals(data: dict[str, dict[int, int]], n_steps: int, out_dir: Path) -> None:
    names = _ordered_names(set(data))
    totals = [sum(data[n].values()) for n in names]
    order = np.argsort(totals)  # smallest at bottom, largest at top
    names = [names[i] for i in order]
    totals = [totals[i] for i in order]

    fig, ax = plt.subplots(figsize=(10, max(3, 0.45 * len(names) + 1.5)))
    y = np.arange(len(names))
    ax.barh(y, totals, color="#2a78d6", height=0.6)
    for yi, t in zip(y, totals):
        ax.text(t, yi, f" {t}", va="center", fontsize=9, color="#52514e")
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel(f"total firings over {n_steps} steps")
    ax.set_title("Guardrail firings — whole run")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#e5e4e0", linewidth=0.8)
    ax.set_axisbelow(True)

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "guardrail_totals.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", help="Run directory (contains metrics_output/guardrails.csv)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    metrics_dir = run_dir / "metrics_output"
    guardrails_csv = metrics_dir / "guardrails.csv"
    out_dir = run_dir / "plots"

    if not guardrails_csv.exists():
        print(f"No {guardrails_csv} — run predates guardrail counting; nothing to plot.")
        return

    data = _load_guardrails(guardrails_csv)
    if not data:
        print(f"{guardrails_csv} is empty: no guardrail fired during this run. Nothing to plot.")
        return

    max_step = max(s for per_step in data.values() for s in per_step) + 1
    n_steps = _n_steps(metrics_dir / "steps.csv", max_step)

    plot_by_step(data, n_steps, out_dir)
    plot_totals(data, n_steps, out_dir)


if __name__ == "__main__":
    main()
