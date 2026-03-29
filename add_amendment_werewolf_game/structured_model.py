# -*- coding: utf-8 -*-
"""The structured output models used in the amendment-enabled werewolf game.
狼人杀修正案版本使用的结构化输出模型。
"""
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from agentscope.agent import AgentBase


class DiscussionModel(BaseModel):
    """The output format for discussion. / 讨论环节的输出格式。"""

    reach_agreement: bool = Field(
        description="Whether you have reached an agreement or not",
    )


class GameConfig(BaseModel):
    """Game-level configurable rules. / 游戏级可配置规则。"""

    max_game_round: int = Field(default=30, ge=10, le=50)
    max_werewolf_discussion: int = Field(default=3, ge=1, le=5)
    witch_self_heal: bool = Field(default=False)
    hunter_on_poison: bool = Field(default=False)
    first_day_last_words: bool = Field(default=True)


class StanceModel(BaseModel):
    """Agent stance after debate. / 辩论后的 Agent 表态。"""

    rule: Literal[1, 2, 3, 4, 5] = Field(
        description="Which rule number you support changing (1-5)",
    )
    value: str = Field(
        description=(
            "The new value you want for this rule. "
            "For bool rules (3,4,5): 'true' or 'false'. "
            "For int rules (1,2): a number like '20'."
        ),
    )


class AmendmentVote(BaseModel):
    """Formal vote on the top amendment. / 对最热门修正案的正式投票。"""

    approve: bool = Field(
        description="Whether you approve this amendment",
    )


class AmendmentProposal(BaseModel):
    """Internal amendment proposal. / 内部修正案对象。"""

    rule: Literal[
        "max_game_round",
        "max_werewolf_discussion",
        "witch_self_heal",
        "hunter_on_poison",
        "first_day_last_words",
    ] = Field(description="Which rule to change")
    value: str = Field(description="New value for the rule")
    reason: str = Field(description="Why this change")


def get_vote_model(agents: list[AgentBase]) -> type[BaseModel]:
    """Get the vote model by player names. / 根据玩家名称生成投票模型。"""

    class VoteModel(BaseModel):
        """The vote output format. / 投票输出格式。"""

        vote: Literal[tuple(_.name for _ in agents)] = Field(  # type: ignore
            description="The name of the player you want to vote for",
        )

    return VoteModel


class WitchResurrectModel(BaseModel):
    """The output format for witch resurrect action. / 女巫救人操作的输出格式。"""

    resurrect: bool = Field(
        description="Whether you want to resurrect the player",
    )


def get_poison_model(agents: list[AgentBase]) -> type[BaseModel]:
    """Get the poison model by player names. / 根据玩家名称生成毒药模型。"""

    class WitchPoisonModel(BaseModel):
        """The output format for witch poison action. / 女巫毒药操作的输出格式。"""

        poison: bool = Field(
            description="Do you want to use the poison potion",
        )
        name: Literal[tuple(_.name for _ in agents)] | None = Field(  # type: ignore
            description=(
                "The name of the player you want to poison, if you "
                "don't want to poison anyone, just leave it empty"
            ),
            default=None,
        )

        @model_validator(mode="before")
        def clear_name_if_no_poison(cls, values: dict) -> dict:
            """Clear name if no poison is used. / 不使用毒药时清空名字。"""
            if isinstance(values, dict) and not values.get("poison"):
                values["name"] = None
            return values

    return WitchPoisonModel


def get_seer_model(agents: list[AgentBase]) -> type[BaseModel]:
    """Get the seer model by player names. / 根据玩家名称生成预言家模型。"""

    class SeerModel(BaseModel):
        """The output format for seer action. / 预言家操作的输出格式。"""

        name: Literal[tuple(_.name for _ in agents)] = Field(  # type: ignore
            description="The name of the player you want to check",
        )

    return SeerModel


def get_hunter_model(agents: list[AgentBase]) -> type[BaseModel]:
    """Get the hunter model by player agents. / 根据玩家生成猎人模型。"""

    class HunterModel(BaseModel):
        """The output format for hunter action. / 猎人操作的输出格式。"""

        shoot: bool = Field(
            description="Whether you want to use the shooting ability or not",
        )
        name: Literal[tuple(_.name for _ in agents)] | None = Field(  # type: ignore
            description=(
                "The name of the player you want to shoot, if you "
                "don't want to the ability, just leave it empty"
            ),
            default=None,
        )

        @model_validator(mode="before")
        def clear_name_if_no_shoot(cls, values: dict) -> dict:
            """If shoot is false, set name to None. / 不开枪时清空名字。"""
            if isinstance(values, dict) and not values.get("shoot"):
                values["name"] = None
            return values

    return HunterModel


def apply_amendment(
    config: GameConfig,
    proposal: AmendmentProposal,
) -> GameConfig:
    """Apply a passed amendment to the current config.
    将通过的修正案应用到当前配置。
    """
    current = config.model_dump()
    field_info = GameConfig.model_fields[proposal.rule]
    field_type = field_info.annotation

    if field_type is bool:
        normalized = proposal.value.strip().lower()
        if normalized in ("true", "1", "yes"):
            new_value = True
        elif normalized in ("false", "0", "no"):
            new_value = False
        else:
            raise ValueError(f"Invalid boolean value: {proposal.value}")
    elif field_type is int:
        new_value = int(proposal.value)
    else:
        new_value = proposal.value

    current[proposal.rule] = new_value
    return GameConfig(**current)
