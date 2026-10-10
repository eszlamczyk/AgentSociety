"""
Guardrail counters for the internet example.

Every place where a bad LLM response (or a flaky simulator RPC) is caught and
the simulation degrades gracefully instead of crashing calls `bump(<name>)`.
`internet.py` drains the counters once per step via `snapshot_and_reset()` and
`metrics/collect.py` writes them to `metrics_output/guardrails.csv`, so a run
shows *how often* the weak model had to be rescued, not just whether the run
survived. `metrics/guardrail_analysis.py` plots that file.

Two sources feed the counters:

1. Explicit `bump()` calls from our own code under `examples/internet/`
   (per-agent tick catch-all, satisfaction evaluator retries, MoveBlock
   place-analysis fallback, GetPerson RPC failures, website-selection
   fallback).
2. A `logging.Filter` on the "agentsociety" logger that recognises the
   vendored blocks' own fallback warnings by message prefix, so the vendored
   code's silent fallbacks (random POI category, random travel radius, plan
   parse failures, social-block errors, ...) get counted without touching
   `packages/agentsociety/`. Install it once with `install_log_counter()`.
   Only the main process logs these (block code runs in-process; the Ray
   `LLMActor`s only emit transport-level warnings, which `llm_log`'s error
   columns already cover).

Counter names are free-form strings; `guardrails.csv` is long-format
(step, guardrail, count) so adding a new name never changes a header.
"""

import logging
from collections import Counter

from agentsociety.logger import get_logger

_per_step: Counter = Counter()
_cumulative: Counter = Counter()


def bump(name: str, n: int = 1) -> None:
    """Record `n` firings of guardrail `name` for the current step."""
    _per_step[name] += n
    _cumulative[name] += n


def snapshot_and_reset() -> dict[str, int]:
    """Return this step's firings as a plain dict and clear the per-step tally."""
    snap = dict(_per_step)
    _per_step.clear()
    return snap


def totals() -> dict[str, int]:
    """Cumulative firings since process start (never reset)."""
    return dict(_cumulative)


# Message prefix -> counter name, for warnings the vendored blocks emit right
# before falling back. Matched with str.startswith on the formatted message.
# Strings must track packages/agentsociety/agentsociety/cityagent/blocks/*.py.
_VENDORED_FALLBACK_PREFIXES: tuple[tuple[str, str], ...] = (
    # plan_block.py — bad plan JSON; forward() returns None, agent idles a tick
    ("Error parsing guidance selection response", "vendored_plan_guidance_parse"),
    ("Error parsing detailed plan", "vendored_plan_detail_parse"),
    # needs_block.py — initial satisfaction / per-tick reflection parse failures
    ("Initial response error", "vendored_needs_initial_parse"),
    ("Error processing reflection response", "vendored_needs_reflection_parse"),
    ("Error processing evaluation response", "vendored_needs_evaluation_parse"),
    # mobility_block.py PlaceSelectionBlock — random category / 10km radius fallback
    ("MobilityBlock: Level 1 selection failed", "vendored_mobility_level1_random"),
    ("MobilityBlock: Level 2 selection failed", "vendored_mobility_level2_random"),
    ("MobilityBlock: Radius selection failed", "vendored_mobility_radius_default"),
    # other_block.py (SleepBlock, still vendored) and our OtherNoneBlock both log
    # this exact prefix before the random.randint(1, 180) duration fallback
    ("An error occurred while evaluating the response at parse time", "other_duration_random"),
    # social_block.py
    ("Error parsing find person response", "vendored_social_find_person_parse"),
    ("Error in finding person", "vendored_social_block_error"),
    ("Error in sending message", "vendored_social_block_error"),
    ("Error in social block", "vendored_social_block_error"),
    # societyagent.py — cognition/emotion update swallowed, step-time parse
    ("Check_and_update_step (emotion_update)", "vendored_emotion_update_failed"),
    ("Error in check_and_update_step", "vendored_step_time_parse"),
)


class _VendoredFallbackCounter(logging.Filter):
    """Counts known fallback warnings; never suppresses them (always returns True)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            try:
                msg = record.getMessage()
            except Exception:
                return True
            for prefix, name in _VENDORED_FALLBACK_PREFIXES:
                if msg.startswith(prefix):
                    bump(name)
                    break
        return True


def install_log_counter() -> None:
    """Attach the vendored-fallback counter to the agentsociety logger (idempotent)."""
    logger = get_logger()
    if not any(isinstance(f, _VendoredFallbackCounter) for f in logger.filters):
        logger.addFilter(_VendoredFallbackCounter())
