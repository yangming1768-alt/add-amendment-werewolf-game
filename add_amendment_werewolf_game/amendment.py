# -*- coding: utf-8 -*-
"""Amendment phase implementation. / 修正案阶段实现。"""
from collections import Counter
from typing import Literal, cast

from agentscope.agent import ReActAgent
from agentscope.pipeline import MsgHub, fanout_pipeline, sequential_pipeline

from structured_model import (
    AmendmentProposal,
    AmendmentVote,
    GameConfig,
    StanceModel,
    apply_amendment,
)
from utils import EchoAgent

RULE_NAMES = {
    1: "max_game_round",
    2: "max_werewolf_discussion",
    3: "witch_self_heal",
    4: "hunter_on_poison",
    5: "first_day_last_words",
}

RuleName = Literal[
    "max_game_round",
    "max_werewolf_discussion",
    "witch_self_heal",
    "hunter_on_poison",
    "first_day_last_words",
]


def build_rules_announcement(config: GameConfig) -> str:
    """Build the rules announcement message. / 构建规则公告消息。"""
    return (
        "=== AMENDMENT PHASE: The following 5 rules can be amended ===\n\n"
        f"[Rule 1] max_game_round (最大游戏轮数)\n"
        f"  Meaning: How many night-day cycles before the game ends in a draw.\n"
        f"  Current: {config.max_game_round}\n"
        f"  Range: 10 ~ 50 (integer)\n\n"
        f"[Rule 2] max_werewolf_discussion (狼人讨论轮数)\n"
        f"  Meaning: How many discussion rounds each werewolf gets per night before voting.\n"
        f"  Current: {config.max_werewolf_discussion}\n"
        f"  Range: 1 ~ 5 (integer)\n\n"
        f"[Rule 3] witch_self_heal (女巫自救)\n"
        f"  Meaning: Whether the witch can use her healing potion on herself when killed by werewolves.\n"
        f"  Current: {str(config.witch_self_heal).lower()}\n"
        f"  Options: true / false\n\n"
        f"[Rule 4] hunter_on_poison (猎人被毒开枪)\n"
        f"  Meaning: Whether the hunter can still shoot when killed by witch's poison.\n"
        f"  Current: {str(config.hunter_on_poison).lower()}\n"
        f"  Options: true / false\n\n"
        f"[Rule 5] first_day_last_words (第一夜遗言)\n"
        f"  Meaning: Whether the player killed on the first night can leave a final statement.\n"
        f"  Current: {str(config.first_day_last_words).lower()}\n"
        f"  Options: true / false\n\n"
        "You will now debate which rule to change and to what value."
    )


def find_top_proposal(stance_msgs: list) -> tuple[int, str, int]:
    """Find the most popular (rule, value) combo. / 找到最热门的 (规则, 值) 组合。"""
    combos = []
    for msg in stance_msgs:
        rule = msg.metadata.get("rule")
        value = msg.metadata.get("value")
        if rule is not None and value is not None:
            combos.append((rule, str(value)))

    if not combos:
        raise ValueError("No valid stances found in messages")

    counter = Counter(combos)
    (top_rule, top_value), vote_count = counter.most_common(1)[0]
    return top_rule, top_value, vote_count


async def amendment_phase(
    agents: list[ReActAgent],
    config: GameConfig,
    moderator: EchoAgent | None = None,
) -> GameConfig:
    """Execute the complete amendment phase. / 执行完整修正案阶段。"""
    if moderator is None:
        moderator = EchoAgent()

    assert len(agents) == 9, "Amendment phase requires exactly 9 agents"

    async with MsgHub(participants=agents) as amendment_hub:
        await amendment_hub.broadcast(
            await moderator(build_rules_announcement(config)),
        )

        amendment_hub.set_auto_broadcast(True)
        await amendment_hub.broadcast(
            await moderator(
                "Now debate which rule to change. You have 3 rounds to discuss. "
                "State which rule you support changing, the new value, and your reason."
            ),
        )
        for round_idx in range(3):
            await amendment_hub.broadcast(
                await moderator(f"--- Debate Round {round_idx + 1} ---"),
            )
            await sequential_pipeline(agents)
        amendment_hub.set_auto_broadcast(False)

        stance_msgs = await fanout_pipeline(
            agents,
            msg=await moderator(
                "Debate is over. Now state your position: which ONE rule do you want "
                "to change, and to what value?"
            ),
            structured_model=StanceModel,
            enable_gather=False,
        )

        top_rule, top_value, top_count = find_top_proposal(stance_msgs)
        await amendment_hub.broadcast(
            await moderator(
                f"Stance results: Rule {top_rule} ({RULE_NAMES[top_rule]}) -> {top_value} "
                f"received the most support ({top_count}/9 stances). "
                "Now entering formal vote on this amendment."
            ),
        )

        vote_msgs = await fanout_pipeline(
            agents,
            msg=await moderator(
                f"FORMAL VOTE: Change Rule {top_rule} ({RULE_NAMES[top_rule]}) "
                f"from {getattr(config, RULE_NAMES[top_rule])} to {top_value}. "
                "Do you approve this amendment?"
            ),
            structured_model=AmendmentVote,
            enable_gather=False,
        )

        approvals = sum(1 for msg in vote_msgs if msg.metadata.get("approve"))
        total = len(agents)
        if approvals > total / 2:
            proposal = AmendmentProposal(
                rule=cast(RuleName, RULE_NAMES[top_rule]),
                value=top_value,
                reason=f"Passed by vote {approvals}/{total}",
            )
            try:
                new_config = apply_amendment(config, proposal)
                await amendment_hub.broadcast(
                    await moderator(
                        f"Amendment PASSED ({approvals}/{total}): "
                        f"{proposal.rule} changed to {proposal.value}."
                    ),
                )
                return new_config
            except Exception as exc:
                await amendment_hub.broadcast(
                    await moderator(
                        f"Amendment passed vote but was rejected by config validation: {exc}"
                    ),
                )
                return config

        await amendment_hub.broadcast(
            await moderator(
                f"Amendment REJECTED ({approvals}/{total}): "
                f"{RULE_NAMES[top_rule]} stays at {getattr(config, RULE_NAMES[top_rule])}."
            ),
        )
        return config
