"""
Plan generation logging.

Writes one record per generated plan to plan_logs.jsonl.
Kept separate from device_logger / position logging because plans are a
different unit of analysis — they capture agent intent and step composition
regardless of whether any physical movement follows.
"""

import datetime
import json
import os
import threading
from typing import Optional

PLAN_LOG_DIR = os.environ.get("PLAN_LOG_DIR", "plan_logs")
os.makedirs(PLAN_LOG_DIR, exist_ok=True)

PLAN_LOG_PATH = os.path.join(PLAN_LOG_DIR, "plan_logs.jsonl")
_plan_log_lock = threading.Lock()

# Same append-mode-persists-across-runs issue as antennas.py's logs (see
# current_changelog.md). Set CLEAR_LOGS_ON_START=1 to truncate once here at
# import time, before any run writes to it.
if os.environ.get("CLEAR_LOGS_ON_START", "0") == "1":
    open(PLAN_LOG_PATH, "w").close()
    print(f"$DEBUG$ - CLEAR_LOGS_ON_START=1: truncated {PLAN_LOG_PATH}")


_SATISFACTION_KEYS = (
    "hunger_satisfaction",
    "energy_satisfaction",
    "safety_satisfaction",
    "social_satisfaction",
)


def log_plan_generated(
    agent_id: int,
    agent_name: str,
    sim_time: str,
    plan_target: str,
    steps: list[dict],
    current_need: Optional[str] = None,
    emotion: Optional[str] = None,
    satisfaction_before: Optional[dict] = None,
    satisfaction_after: Optional[dict] = None,
):
    """
    Log a newly generated plan.

    Args:
        agent_id:     Unique agent identifier.
        agent_name:   Human-readable agent name.
        sim_time:     Simulated time string, e.g. "day0 08:15:00".
        plan_target:  High-level goal, e.g. "Work", "Eat outside".
        steps:        List of step dicts from the plan, each with at minimum
                      'intention' and 'type' keys, optionally 'device_usage'.
        current_need: The need that triggered this plan (hungry/tired/safe/social/whatever).
        emotion:      Agent's emotion_types string at plan generation time.
        satisfaction_before: The four *_satisfaction values (0-1) captured at the
                      start of this tick, before needs_block's decay + LLM
                      evaluation ran. Optionally includes 'current_need'.
        satisfaction_after:  The four *_satisfaction values immediately after
                      needs_block ran this same tick — i.e. the values that
                      determined this plan's need. Used to see whether a
                      completed/failed plan actually raised satisfaction
                      before the same need re-triggered a new plan.
    """
    summarised_steps = [
        {
            "intention": s.get("intention"),
            "type": s.get("type"),
            "has_device_usage": s.get("device_usage") is not None,
        }
        for s in steps
    ]

    n_steps = len(summarised_steps)
    n_mobility = sum(1 for s in summarised_steps if s["type"] == "mobility")
    n_device = sum(1 for s in summarised_steps if s["has_device_usage"])

    satisfaction_delta = None
    if satisfaction_before and satisfaction_after:
        satisfaction_delta = {
            k: round(satisfaction_after[k] - satisfaction_before[k], 4)
            for k in _SATISFACTION_KEYS
            if k in satisfaction_before and k in satisfaction_after
        }

    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "sim_time": sim_time,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "need": current_need,
        "need_before": satisfaction_before.get("current_need") if satisfaction_before else None,
        "emotion": emotion,
        "plan_target": plan_target,
        "n_steps": n_steps,
        "n_mobility_steps": n_mobility,
        "n_device_steps": n_device,
        "has_any_mobility": n_mobility > 0,
        "satisfaction_before": (
            {k: satisfaction_before[k] for k in _SATISFACTION_KEYS if k in satisfaction_before}
            if satisfaction_before else None
        ),
        "satisfaction_after": (
            {k: satisfaction_after[k] for k in _SATISFACTION_KEYS if k in satisfaction_after}
            if satisfaction_after else None
        ),
        "satisfaction_delta": satisfaction_delta,
        "steps": summarised_steps,
    }

    with _plan_log_lock:
        with open(PLAN_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
