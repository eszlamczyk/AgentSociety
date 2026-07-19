"""
Reliable mobility execution.

The vendored MobilityBlock (agentsociety.cityagent.blocks.mobility_block)
dispatches each [mobility] plan step to exactly ONE of three sub-blocks per
tick, chosen by an LLM function call: PlaceSelectionBlock (only *picks* a
destination, never moves the agent), MoveBlock (calls
environment.set_aoi_schedules to actually move), or MobilityNoneBlock (no-op).

check_and_update_step() only checks whether a step's evaluation dict exists
and its consumed_time has elapsed — it has no notion of "did MoveBlock
actually run". So if the dispatcher picks PlaceSelectionBlock and the plan
gets interrupted (e.g. by a need change) before MoveBlock is ever dispatched
on a later tick, the [mobility] step is marked complete having only chosen a
destination — no environment call, no position change. See findings.md
finding #2: 27/45 (100-agent run) and 13/19 (20-agent run) agents with
mobility-containing plans never produced a single position log entry.

MobilityBlock here removes the per-tick dispatcher choice for the two real
sub-actions: every [mobility] step always runs PlaceSelectionBlock followed
immediately by MoveBlock in the same call, so a step can never be marked done
having only selected a destination.
"""

import random

from agentsociety.agent import DotDict
from agentsociety.cityagent.blocks.mobility_block import (
    MobilityBlock as _VendoredMobilityBlock,
)


class MobilityBlock(_VendoredMobilityBlock):
    async def forward(self, agent_context: DotDict):
        self.trigger_time += 1
        context = agent_context | self.context

        select_result = await self.place_selection_block.forward(context)
        if not select_result.get("success", True):
            return self.OutputType(
                success=False,
                evaluation=select_result.get(
                    "evaluation", "Failed to select a destination"
                ),
                consumed_time=select_result.get("consumed_time", random.randint(1, 30)),
                node_id=select_result.get("node_id"),
            )

        # place_selection_block wrote context["next_place"] in place; move_block
        # reads it from the same context object.
        move_result = await self.move_block.forward(context)

        consumed_time = select_result.get("consumed_time", 0) + move_result.get(
            "consumed_time", 0
        )
        return self.OutputType(
            success=move_result.get("success", True),
            evaluation=move_result.get("evaluation", "Moved"),
            consumed_time=consumed_time,
            node_id=move_result.get("node_id"),
        )
