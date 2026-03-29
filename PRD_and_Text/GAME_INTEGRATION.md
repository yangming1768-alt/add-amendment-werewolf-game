# 游戏代码完整调用 — 执行说明

> Game Integration Spec
> 本文档定义如何把修正案阶段和配置层接入当前狼人杀代码，并在单局范围内完成完整调用。

---

## 一、目标

当前目标是形成以下单局执行链路：

```python
config = GameConfig()
config = await amendment_phase(players, config)
await werewolves_game(players, config)
```

也就是：

1. 先创建默认配置。
2. 在正式开局前运行一次修正案阶段。
3. 如果修正案通过，则更新 config。
4. 用最终 config 启动当前这一局狼人杀。

当前**不包含多轮循环**。

---

## 二、改动文件清单

| 文件 | 作用 | 改动 |
|------|------|------|
| `structured_model.py` | 定义结构化对象 | 新增 `GameConfig`, `StanceModel`, `AmendmentVote`, `AmendmentProposal` |
| `game.py` | 游戏规则执行层 | `werewolves_game()` 新增 `config` 参数，5 处逻辑改为读取 `config.xxx` |
| `main.py` | 主入口 | 在调用 `werewolves_game()` 前增加 `amendment_phase()` |
| `amendment.py` 或 `game.py` | 修正案流程 | 新增 `amendment_phase()`, `build_rules_announcement()`, `find_top_proposal()` |

---

## 三、main.py 接入方式

### 当前 main.py 的核心逻辑

```python
players = [get_official_agents(f"Player{_ + 1}") for _ in range(9)]
session = JSONSession(save_dir="./checkpoints")
await session.load_session_state(...)
await werewolves_game(players)
await session.save_session_state(...)
```

### 接入后的目标逻辑

```python
players = [get_official_agents(f"Player{_ + 1}") for _ in range(9)]
session = JSONSession(save_dir="./checkpoints")
await session.load_session_state(...)

config = GameConfig()
config = await amendment_phase(players, config)
await werewolves_game(players, config)

await session.save_session_state(...)
```

### 完整示例

```python
from structured_model import GameConfig
from amendment import amendment_phase
from game import werewolves_game


async def main() -> None:
    players = [get_official_agents(f"Player{_ + 1}") for _ in range(9)]

    session = JSONSession(save_dir="./checkpoints")
    await session.load_session_state(
        session_id="players_checkpoint",
        **{player.name: player for player in players},
    )

    config = GameConfig()
    config = await amendment_phase(players, config)
    await werewolves_game(players, config)

    await session.save_session_state(
        session_id="players_checkpoint",
        **{player.name: player for player in players},
    )
```

---

## 四、game.py 的接入方式

### 4.1 函数签名改造

原来：

```python
async def werewolves_game(agents: list[ReActAgent]) -> None:
```

改为：

```python
from structured_model import GameConfig


async def werewolves_game(
    agents: list[ReActAgent],
    config: GameConfig | None = None,
) -> None:
    if config is None:
        config = GameConfig()
```

### 为什么要保留 `config=None`

这样做有两个好处：

1. **向后兼容**：旧代码仍然可以直接 `await werewolves_game(players)`。
2. **实现渐进改造**：即使修正案阶段还没写完，游戏主流程仍可运行。

---

## 五、game.py 中 5 处规则读取点

### 1. 最大游戏轮数

原来：

```python
for _ in range(MAX_GAME_ROUND):
```

改为：

```python
for _ in range(config.max_game_round):
```

作用：控制整局最多跑多少个“夜+天”循环。

### 2. 狼人讨论轮数

原来：

```python
for _ in range(1, MAX_DISCUSSION_ROUND * n_werewolves + 1):
```

改为：

```python
for _ in range(1, config.max_werewolf_discussion * n_werewolves + 1):
```

作用：控制每晚狼人私聊最多轮转几轮。

### 3. 女巫能否自救

原来：

```python
if healing and killed_player != agent.name:
```

改为：

```python
if healing and (config.witch_self_heal or killed_player != agent.name):
```

作用：`config.witch_self_heal=True` 时，女巫即使自己被杀也能进入救人逻辑。

### 4. 猎人被毒能否开枪

原来：

```python
if (
    killed_player == agent.name
    and poisoned_player != agent.name
):
```

改为：

```python
if (
    killed_player == agent.name
    and (config.hunter_on_poison or poisoned_player != agent.name)
):
```

作用：`config.hunter_on_poison=True` 时，被毒死的猎人仍可进入开枪逻辑。

### 5. 第一夜遗言

原来：

```python
if killed_player and first_day:
```

改为：

```python
if killed_player and first_day and config.first_day_last_words:
```

作用：增加一个总开关，关闭后整段遗言逻辑直接跳过。

---

## 六、单局完整时序

### 时序图

```
main.py
  │
  ├─ 创建 9 个 Agent
  │
  ├─ 从 JSONSession 加载状态
  │
  ├─ config = GameConfig()                  ← 默认规则
  │
  ├─ config = amendment_phase(players, config)
  │      │
  │      ├─ 广播 5 条可修改规则
  │      ├─ 3 轮辩论
  │      ├─ 表态
  │      ├─ 统计最热门提案
  │      ├─ 正式投票
  │      └─ apply_amendment() → 返回新 config
  │
  ├─ werewolves_game(players, config)
  │      │
  │      ├─ 按 config.max_game_round 控制整局轮数
  │      ├─ 按 config.max_werewolf_discussion 控制狼人私聊轮数
  │      ├─ 按 config.witch_self_heal 控制女巫自救
  │      ├─ 按 config.hunter_on_poison 控制猎人被毒开枪
  │      └─ 按 config.first_day_last_words 控制第一夜遗言
  │
  └─ 保存 JSONSession
```

---

## 七、推荐的模块边界

### 方案 A：全部先放在现有文件中

适合快速验证。

- `structured_model.py`：结构化模型 + `GameConfig`
- `game.py`：游戏规则读取 `config`
- `main.py`：增加 `config = GameConfig()` 和 `amendment_phase()` 调用
- `game.py` 或 `main.py`：临时放 `amendment_phase()`

优点：
- 改动少
- 上手快

缺点：
- 逻辑耦合偏重

### 方案 B：把修正案流程单独放进 `amendment.py`

推荐长期采用。

- `structured_model.py`：纯数据结构
- `amendment.py`：修正案流程实现
- `game.py`：纯游戏执行逻辑
- `main.py`：编排入口

优点：
- 职责清晰
- 后续扩展方便

---

## 八、当前不做的部分

当前文件只描述**单局接入**，明确不做：

- 多轮外层循环
- config 跨局累积
- 规则历史版本管理
- 自动回滚
- 规则变更日志持久化

如果未来要做自迭代闭环，可以在 `main.py` 外层再包一层多局调度；但不属于当前接入目标。

---

## 九、与其他文档的关系

- 修正案阶段流程见 `AMENDMENT_PHASE.md`
- 配置注入细节见 `CONFIG_INJECTION.md`

本文件只回答一个问题：

**“当前单局版本里，修正案阶段和 GameConfig 如何接入现有狼人杀代码？”**
