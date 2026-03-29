# -*- coding: utf-8 -*-
"""Utility functions for the werewolf game. / 狼人杀游戏工具函数。"""
from collections import defaultdict
from typing import Any

import numpy as np

from prompt import EnglishPrompts as Prompts

from agentscope.message import Msg, AudioBlock
from agentscope.agent import ReActAgent, AgentBase
from agentscope.tts import TTSModelBase

MAX_GAME_ROUND = 30
MAX_DISCUSSION_ROUND = 3


def majority_vote(votes: list[str]) -> tuple:
    """Return the vote with the most counts. / 返回得票最多的选项。"""
    result = max(set(votes), key=votes.count)
    names, counts = np.unique(votes, return_counts=True)
    conditions = ", ".join(
        [f"{name}: {count}" for name, count in zip(names, counts)],
    )
    return result, conditions


def names_to_str(agents: list[str] | list[ReActAgent]) -> str:
    """Return a string of agent names. / 将 Agent 名称列表格式化为字符串。"""
    if not agents:
        return ""

    names = [getattr(agent, "name", agent) for agent in agents]
    if len(names) == 1:
        return str(names[0])

    return ", ".join([*names[:-1], "and " + str(names[-1])])


class EchoAgent(AgentBase):
    """Echo agent that repeats the input message. / 回声 Agent，仅转发输入消息（主持人）。"""

    def __init__(self, tts_model: TTSModelBase | None = None) -> None:
        super().__init__()
        self.name = "Moderator"
        self.tts_model = tts_model

    async def reply(self, content: str) -> Msg:
        """Repeat the input content with its name and role. / 以主持人身份转发消息。"""
        msg = Msg(self.name, content, role="assistant")
        speech: AudioBlock | list[AudioBlock] | None = None
        if self.tts_model:
            tts_res = await self.tts_model.synthesize(msg)
            if self.tts_model.stream:
                async for tts_chunk in tts_res:
                    speech = tts_chunk.content
                    await self.print(msg, False, speech=speech)
            else:
                speech = tts_res.content
        await self.print(msg, True, speech=speech)
        return msg

    async def handle_interrupt(self, *args: Any, **kwargs: Any) -> Msg:
        """Handle interrupt. / 处理中断。"""

    async def observe(self, msg: Msg | list[Msg] | None) -> None:
        """Observe the user's message. / 观察消息。"""


class Players:
    """Maintain the players' status. / 维护玩家状态。"""

    def __init__(self) -> None:
        self.name_to_role = {}
        self.role_to_names = defaultdict(list)
        self.name_to_agent = {}
        self.werewolves = []
        self.villagers = []
        self.seer = []
        self.hunter = []
        self.witch = []
        self.current_alive = []
        self.all_players = []

    def add_player(self, player: ReActAgent, role: str) -> None:
        self.name_to_role[player.name] = role
        self.name_to_agent[player.name] = player
        self.role_to_names[role].append(player.name)
        self.all_players.append(player)
        if role == "werewolf":
            self.werewolves.append(player)
        elif role == "villager":
            self.villagers.append(player)
        elif role == "seer":
            self.seer.append(player)
        elif role == "hunter":
            self.hunter.append(player)
        elif role == "witch":
            self.witch.append(player)
        else:
            raise ValueError(f"Unknown role: {role}")
        self.current_alive.append(player)

    def update_players(self, dead_players: list[str | None]) -> None:
        self.werewolves = [_ for _ in self.werewolves if _.name not in dead_players]
        self.villagers = [_ for _ in self.villagers if _.name not in dead_players]
        self.seer = [_ for _ in self.seer if _.name not in dead_players]
        self.hunter = [_ for _ in self.hunter if _.name not in dead_players]
        self.witch = [_ for _ in self.witch if _.name not in dead_players]
        self.current_alive = [_ for _ in self.current_alive if _.name not in dead_players]

    def print_roles(self) -> None:
        print("Roles:")
        for name, role in self.name_to_role.items():
            print(f" - {name}: {role}")

    def check_winning(self) -> str | None:
        true_roles = (
            f'{names_to_str(self.role_to_names["werewolf"])} are werewolves, '
            f'{names_to_str(self.role_to_names["villager"])} are villagers, '
            f'{names_to_str(self.role_to_names["seer"])} is the seer, '
            f'{names_to_str(self.role_to_names["hunter"])} is the hunter, '
            f'and {names_to_str(self.role_to_names["witch"])} is the witch.'
        )

        if len(self.werewolves) * 2 >= len(self.current_alive):
            return Prompts.to_all_wolf_win.format(
                n_alive=len(self.current_alive),
                n_werewolves=len(self.werewolves),
                true_roles=true_roles,
            )
        if self.current_alive and not self.werewolves:
            return Prompts.to_all_village_win.format(true_roles=true_roles)
        return None
