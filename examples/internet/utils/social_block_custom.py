"""
Network-aware social messaging.

The vendored MessageBlock (agentsociety.cityagent.blocks.social_block) sends
a real chat message via self.agent.send_message_to_agent(), but never touches
this example's antenna/device logging system (utils/antennas.py,
utils/device_logger.py) — that only fires from InternetAgent.step_execution()
when a plan step's LLM-generated JSON happens to carry a device_usage field.
Measured on a 100-agent partial run: 17,810 real do_chat message deliveries
vs. only 408 "social"-tagged device_usage_logs.jsonl entries — ~98% of actual
messaging traffic left no IP/antenna trace at all.

MessageBlock here logs a real network event (own device/IP/antenna, peer_id,
no message content) on every successful outgoing send, independent of
whatever the planner attached to the step. SocialBlock swaps the vendored
MessageBlock instance for this one; SocialBlock.forward() itself is
unchanged (it already calls self.message_block.set_agent(self.agent) each
call, so agent access "just works" via inheritance).

The inbound half of this (do_chat) is handled directly in InternetAgent
(internetagent.py's do_chat override), since do_chat lives on the agent
class, not a block.
"""

from agentsociety.cityagent.blocks.social_block import (
    MessageBlock as _VendoredMessageBlock,
    SocialBlock as _VendoredSocialBlock,
)


class MessageBlock(_VendoredMessageBlock):
    async def forward(self, context):
        target = context.get("target") if context else None
        if not target:
            find_result = await self.find_person_block.forward(context)
            if not find_result["success"]:
                return find_result
            target = find_result["target"]
            context["target"] = target

        result = await super().forward(context)
        if result.get("success"):
            await self.agent.log_message_event(
                event="message_sent",
                peer_id=target,
                action_description="Sent a chat message",
            )
        return result


class SocialBlock(_VendoredSocialBlock):
    def __init__(self, toolbox, agent_memory, block_params=None):
        super().__init__(
            toolbox=toolbox, agent_memory=agent_memory, block_params=block_params
        )
        self.message_block = MessageBlock(toolbox, agent_memory)
        self.dispatcher.register_blocks([self.message_block])
