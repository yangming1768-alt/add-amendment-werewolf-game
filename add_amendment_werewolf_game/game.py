# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches, too-many-statements, no-name-in-module
"""A werewolf game implemented by agentscope with amendment config support.
基于 AgentScope 实现的支持修正案配置的狼人杀游戏。
"""
import numpy as np

from utils import majority_vote, names_to_str, EchoAgent, Players
from structured_model import (
    DiscussionModel,
    GameConfig,
    WitchResurrectModel,
    get_hunter_model,
    get_poison_model,
    get_seer_model,
    get_vote_model,
)
from prompt import EnglishPrompts as Prompts

from agentscope.agent import ReActAgent
from agentscope.pipeline import MsgHub, sequential_pipeline, fanout_pipeline

moderator = EchoAgent()


async def hunter_stage(
    hunter_agent: ReActAgent,
    players: Players,
) -> str | None:
    """Shared hunter action stage. / 共享猎人行动阶段。"""
    msg_hunter = await hunter_agent(
        await moderator(Prompts.to_hunter.format(name=hunter_agent.name)),
        structured_model=get_hunter_model(players.current_alive),
    )
    if msg_hunter.metadata.get("shoot"):
        return msg_hunter.metadata.get("name", None)
    return None


async def werewolves_game(
    agents: list[ReActAgent],
    config: GameConfig | None = None,
) -> None:
    """The main entry of the werewolf game. / 狼人杀游戏主入口。"""
    assert len(agents) == 9, "The werewolf game needs exactly 9 players."
    if config is None:
        config = GameConfig()

    players = Players()
    healing, poison = True, True
    first_day = True

    async with MsgHub(participants=agents) as greeting_hub:
        await greeting_hub.broadcast(
            await moderator(Prompts.to_all_new_game.format(names_to_str(agents))),
        )

    roles = ["werewolf"] * 3 + ["villager"] * 3 + ["seer", "witch", "hunter"]
    np.random.shuffle(agents)
    np.random.shuffle(roles)

    for agent, role in zip(agents, roles):
        await agent.observe(
            await moderator(f"[{agent.name} ONLY] {agent.name}, your role is {role}."),
        )
        players.add_player(agent, role)

    players.print_roles()

    for _ in range(config.max_game_round):
        async with MsgHub(
            participants=players.current_alive,
            enable_auto_broadcast=False,
            name="alive_players",
        ) as alive_players_hub:
            await alive_players_hub.broadcast(await moderator(Prompts.to_all_night))
            killed_player, poisoned_player, shot_player = None, None, None

            async with MsgHub(
                players.werewolves,
                enable_auto_broadcast=True,
                announcement=await moderator(
                    Prompts.to_wolves_discussion.format(
                        names_to_str(players.werewolves),
                        names_to_str(players.current_alive),
                    ),
                ),
                name="werewolves",
            ) as werewolves_hub:
                n_werewolves = len(players.werewolves)
                for turn_idx in range(1, config.max_werewolf_discussion * n_werewolves + 1):
                    res = await players.werewolves[turn_idx % n_werewolves](
                        structured_model=DiscussionModel,
                    )
                    if turn_idx % n_werewolves == 0 and res.metadata.get("reach_agreement"):
                        break

                werewolves_hub.set_auto_broadcast(False)
                msgs_vote = await fanout_pipeline(
                    players.werewolves,
                    msg=await moderator(content=Prompts.to_wolves_vote),
                    structured_model=get_vote_model(players.current_alive),
                    enable_gather=False,
                )
                killed_player, votes = majority_vote([_.metadata.get("vote") for _ in msgs_vote])
                await werewolves_hub.broadcast(
                    [
                        *msgs_vote,
                        await moderator(Prompts.to_wolves_res.format(votes, killed_player)),
                    ],
                )

            await alive_players_hub.broadcast(await moderator(Prompts.to_all_witch_turn))
            for agent in players.witch:
                msg_witch_resurrect = None
                if healing and (config.witch_self_heal or killed_player != agent.name):
                    msg_witch_resurrect = await agent(
                        await moderator(
                            Prompts.to_witch_resurrect.format(
                                witch_name=agent.name,
                                dead_name=killed_player,
                            ),
                        ),
                        structured_model=WitchResurrectModel,
                    )
                    if msg_witch_resurrect.metadata.get("resurrect"):
                        killed_player = None
                        healing = False

                if poison and not (
                    msg_witch_resurrect and msg_witch_resurrect.metadata["resurrect"]
                ):
                    msg_witch_poison = await agent(
                        await moderator(Prompts.to_witch_poison.format(witch_name=agent.name)),
                        structured_model=get_poison_model(players.current_alive),
                    )
                    if msg_witch_poison.metadata.get("poison"):
                        poisoned_player = msg_witch_poison.metadata.get("name")
                        poison = False

            await alive_players_hub.broadcast(await moderator(Prompts.to_all_seer_turn))
            for agent in players.seer:
                msg_seer = await agent(
                    await moderator(
                        Prompts.to_seer.format(
                            agent.name,
                            names_to_str(players.current_alive),
                        ),
                    ),
                    structured_model=get_seer_model(players.current_alive),
                )
                if msg_seer.metadata.get("name"):
                    player = msg_seer.metadata["name"]
                    await agent.observe(
                        await moderator(
                            Prompts.to_seer_result.format(
                                agent_name=player,
                                role=players.name_to_role[player],
                            ),
                        ),
                    )

            for agent in players.hunter:
                if (
                    killed_player == agent.name
                    and (config.hunter_on_poison or poisoned_player != agent.name)
                ):
                    shot_player = await hunter_stage(agent, players)

            dead_tonight = [killed_player, poisoned_player, shot_player]
            players.update_players(dead_tonight)

            if len([_ for _ in dead_tonight if _]) > 0:
                await alive_players_hub.broadcast(
                    await moderator(
                        Prompts.to_all_day.format(names_to_str([_ for _ in dead_tonight if _])),
                    ),
                )

                if killed_player and first_day and config.first_day_last_words:
                    msg_moderator = await moderator(Prompts.to_dead_player.format(killed_player))
                    await alive_players_hub.broadcast(msg_moderator)
                    last_msg = await players.name_to_agent[killed_player]()
                    await alive_players_hub.broadcast(last_msg)
            else:
                await alive_players_hub.broadcast(await moderator(Prompts.to_all_peace))

            res = players.check_winning()
            if res:
                async with MsgHub(players.all_players) as all_players_hub:
                    await all_players_hub.broadcast(await moderator(res))
                break

            await alive_players_hub.broadcast(
                await moderator(Prompts.to_all_discuss.format(names=names_to_str(players.current_alive))),
            )
            alive_players_hub.set_auto_broadcast(True)
            await sequential_pipeline(players.current_alive)
            alive_players_hub.set_auto_broadcast(False)

            msgs_vote = await fanout_pipeline(
                players.current_alive,
                await moderator(Prompts.to_all_vote.format(names_to_str(players.current_alive))),
                structured_model=get_vote_model(players.current_alive),
                enable_gather=False,
            )
            voted_player, votes = majority_vote([_.metadata.get("vote") for _ in msgs_vote])
            voting_msgs = [
                *msgs_vote,
                await moderator(Prompts.to_all_res.format(votes, voted_player)),
            ]

            if voted_player:
                prompt_msg = await moderator(Prompts.to_dead_player.format(voted_player))
                last_msg = await players.name_to_agent[voted_player](prompt_msg)
                voting_msgs.extend([prompt_msg, last_msg])

            await alive_players_hub.broadcast(voting_msgs)

            shot_player = None
            for agent in players.hunter:
                if voted_player == agent.name:
                    shot_player = await hunter_stage(agent, players)
                    if shot_player:
                        await alive_players_hub.broadcast(
                            await moderator(Prompts.to_all_hunter_shoot.format(shot_player)),
                        )

            dead_today = [voted_player, shot_player]
            players.update_players(dead_today)

            res = players.check_winning()
            if res:
                async with MsgHub(players.all_players) as all_players_hub:
                    await all_players_hub.broadcast(await moderator(res))
                break

        first_day = False

    await fanout_pipeline(
        agents=agents,
        msg=await moderator(Prompts.to_all_reflect),
    )
