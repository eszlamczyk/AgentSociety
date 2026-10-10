"""
MetricsCollector — call record() once after each simulation step.

Writes three CSV files incrementally:
  - steps.csv      : one row per step — tick, wall time, tokens, LLM transport
                     error counts, and guardrail_firings (total fallbacks that
                     step, see utils/guardrails.py)
  - agents.csv     : one row per agent-step — tokens and error counts
  - guardrails.csv : long-format (step, guardrail, count), one row per
                     guardrail name that fired that step; absent names = 0
"""

import csv
from pathlib import Path


_STEPS_HEADER = ["step", "tick", "wall_time_s", "input_tokens", "output_tokens",
                 "total_errors", "connection_errors", "openai_errors", "timeout_errors", "other_errors",
                 "guardrail_firings"]
_GUARDRAILS_HEADER = ["step", "guardrail", "count"]
_AGENTS_HEADER = ["step", "agent_id", "input_tokens", "output_tokens",
                  "total_errors", "connection_errors", "openai_errors", "timeout_errors", "other_errors"]


class MetricsCollector:
    def __init__(self, out_dir: str | Path):
        """
        Args:
            out_dir: Directory where steps.csv and agents.csv are written.
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        self._steps_path = out_dir / "steps.csv"
        self._agents_path = out_dir / "agents.csv"
        self._guardrails_path = out_dir / "guardrails.csv"

        # Open for append — write header only if file is new/empty.
        self._steps_f = open(self._steps_path, "a", newline="")
        self._agents_f = open(self._agents_path, "a", newline="")
        self._guardrails_f = open(self._guardrails_path, "a", newline="")

        self._steps_w = csv.writer(self._steps_f)
        self._agents_w = csv.writer(self._agents_f)
        self._guardrails_w = csv.writer(self._guardrails_f)

        if self._steps_path.stat().st_size == 0:
            self._steps_w.writerow(_STEPS_HEADER)
        if self._agents_path.stat().st_size == 0:
            self._agents_w.writerow(_AGENTS_HEADER)
        if self._guardrails_path.stat().st_size == 0:
            self._guardrails_w.writerow(_GUARDRAILS_HEADER)

        self._step_counter = 0

    def record(self, tick: int, wall_time_s: float, llm_log: list,
               guardrails: dict[str, int] | None = None) -> None:
        """
        Aggregate the llm_log from this step and write one row to each CSV.

        Args:
            tick:        Sim time (seconds into day) at the START of the step.
            wall_time_s: Real elapsed seconds for the step.
            llm_log:     The Logs.llm_log list returned by engine.step().
                         Each entry is a dict with keys: agent_id, input_tokens,
                         output_tokens, request_time, consumption, ...
            guardrails:  {guardrail_name: firings} for this step, as returned
                         by utils.guardrails.snapshot_and_reset(). Optional.
        """
        guardrails = guardrails or {}
        guardrail_total = sum(guardrails.values())
        # --- per-step totals ---
        total_in = sum(e["input_tokens"] for e in llm_log)
        total_out = sum(e["output_tokens"] for e in llm_log)
        total_errors = sum(e.get("total_errors", 0) for e in llm_log)
        conn_errors = sum(e.get("error_types", {}).get("connection_error", 0) for e in llm_log)
        oai_errors = sum(e.get("error_types", {}).get("openai_error", 0) for e in llm_log)
        timeout_errors = sum(e.get("error_types", {}).get("timeout_error", 0) for e in llm_log)
        other_errors = sum(e.get("error_types", {}).get("other_error", 0) for e in llm_log)

        self._steps_w.writerow(
            [self._step_counter, tick, round(wall_time_s, 4), total_in, total_out,
             total_errors, conn_errors, oai_errors, timeout_errors, other_errors,
             guardrail_total]
        )
        self._steps_f.flush()

        # --- guardrail firings (long format; only names that fired) ---
        for name in sorted(guardrails):
            self._guardrails_w.writerow([self._step_counter, name, guardrails[name]])
        self._guardrails_f.flush()

        # --- per-agent breakdown ---
        # agent_id=None means a call made outside any agent context (e.g. init).
        agent_totals: dict[int | None, dict] = {}
        for e in llm_log:
            aid = e["agent_id"]
            if aid not in agent_totals:
                agent_totals[aid] = {"input_tokens": 0, "output_tokens": 0,
                                     "total_errors": 0, "connection_errors": 0,
                                     "openai_errors": 0, "timeout_errors": 0, "other_errors": 0}
            agent_totals[aid]["input_tokens"] += e["input_tokens"]
            agent_totals[aid]["output_tokens"] += e["output_tokens"]
            et = e.get("error_types", {})
            agent_totals[aid]["total_errors"] += e.get("total_errors", 0)
            agent_totals[aid]["connection_errors"] += et.get("connection_error", 0)
            agent_totals[aid]["openai_errors"] += et.get("openai_error", 0)
            agent_totals[aid]["timeout_errors"] += et.get("timeout_error", 0)
            agent_totals[aid]["other_errors"] += et.get("other_error", 0)

        for aid, totals in agent_totals.items():
            self._agents_w.writerow(
                [self._step_counter, aid, totals["input_tokens"], totals["output_tokens"],
                 totals["total_errors"], totals["connection_errors"], totals["openai_errors"],
                 totals["timeout_errors"], totals["other_errors"]]
            )
        self._agents_f.flush()

        self._step_counter += 1

    def close(self) -> None:
        self._steps_f.close()
        self._agents_f.close()
        self._guardrails_f.close()
