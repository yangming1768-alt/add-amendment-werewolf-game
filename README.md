# AI 自迭代狼人杀 — Amendment-Enabled Werewolf Game

> 让 AI Agent 不只是玩游戏，还能**协商改变游戏规则**。

本项目 Fork 自 [AgentScope 官方示例 — Werewolf Game](https://github.com/modelscope/agentscope/tree/main/examples/game_werewolf)，在标准 9 人狼人杀基础上，新增了一个**修正案阶段**（Amendment Phase）：9 个 AI Agent 在游戏开始前，通过提案→辩论→表态→投票的流程协商修改游戏规则，通过的修正案注入游戏配置后再开局。

## 项目意义

我们想看到 AI Agent 在相互交互游玩游戏之外，通过引入**提案—辩论—表态—投票**的类似人类进行政治活动的行为来**改变所处的游戏世界**，实现一个闭环：

```text
Agent 游玩 → 交互博弈 → 获得结果 → 协商改变规则 → 再次游玩
```

这不只是一个"AI 打狼人杀"的项目——它探索的是：**当 AI 拥有修改自身运行规则的能力时，会涌现什么行为？** 它们会利用规则修改来为自己的阵营牟利吗？它们的辩论和投票会展现出怎样的策略深度？

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/yangming1768-alt/add-amendment-werewolf-game.git
cd add_amendment_werewolf_game

# 创建虚拟环境（推荐）
python -m venv .venv
# Windows
.venv\Scripts\Activate.ps1
# macOS/Linux
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

本项目使用阿里云 DashScope 的 `qwen3-max` 模型。前往 [阿里云百炼控制台](https://bailian.console.aliyun.com/) 获取 API Key，然后在项目目录下创建 `.env` 文件：

```env
DASHSCOPE_API_KEY=sk-你的密钥
```

### 3. 运行

```bash
python main.py
```

程序会依次执行：

1. **修正案阶段** — 9 个 Agent 辩论并投票修改规则
2. **狼人杀游戏** — 按修改后的规则进行完整对局
3. **自动保存** — 游戏日志保存到 `logs/`，Agent 状态保存到 `checkpoints/`

中途停止运行：在终端按 `Ctrl+C` 即可终止。

## 游戏流程

```text
┌─────────────────────────────────────────────────┐
│              AMENDMENT PHASE (修正案阶段)          │
│                                                   │
│  ① 广播 5 条可修改规则（名称/含义/当前值/范围）       │
│  ② 3 轮自由辩论 (sequential_pipeline)              │
│  ③ 结构化表态：每人选 1 条规则 + 新值 (StanceModel)  │
│  ④ 统计最热门提案                                   │
│  ⑤ 全体正式投票：赞成/反对 (AmendmentVote)          │
│  ⑥ 过半通过 → 注入 GameConfig / 否则维持原样         │
│                                                   │
├─────────────────────────────────────────────────┤
│              WEREWOLF GAME (狼人杀对局)            │
│                                                   │
│  夜晚: 狼人讨论→投票杀人→女巫救人/毒人→预言家查验     │
│  白天: 公告死讯→自由讨论→投票放逐→遗言                │
│  循环直到一方获胜                                    │
└─────────────────────────────────────────────────┘
```

## 5 条可修改规则

| # | 规则名 | 含义 | 默认值 | 范围 |
| --- | --- | --- | --- | --- |
| 1 | `max_game_round` | 最大游戏轮数（超过则平局） | 30 | 10~50 |
| 2 | `max_werewolf_discussion` | 狼人每晚讨论轮数 | 3 | 1~5 |
| 3 | `witch_self_heal` | 女巫能否自救 | false | true/false |
| 4 | `hunter_on_poison` | 猎人被毒死能否开枪 | false | true/false |
| 5 | `first_day_last_words` | 第一夜死者能否留遗言 | true | true/false |

规则通过 `GameConfig`（Pydantic BaseModel）管理，带有 `ge`/`le` 约束确保值合法。修正案通过 `apply_amendment()` 注入，包含类型转换和校验。

## 代码架构

```text
add_amendment_werewolf_game/
├── main.py              # 入口：9 Agent 创建 → 修正案 → 人工确认 → 游戏 → 日志保存
├── amendment.py         # 修正案阶段：辩论 / 表态 / 投票 / 注入
├── game.py              # 狼人杀主循环：夜晚→白天→胜负判定（5 个配置注入点）
├── structured_model.py  # Pydantic 模型：GameConfig + StanceModel + AmendmentVote + 游戏模型
├── utils.py             # EchoAgent(主持人) / Players 状态管理 / majority_vote
├── prompt.py            # 提示词模板（英文）
├── requirements.txt     # 依赖：agentscope, pydantic, numpy, python-dotenv
├── .env                 # API Key（不入 Git）
├── logs/                # 游戏运行日志（按时间戳命名）
└── checkpoints/         # Agent 状态持久化（JSONSession）
```

### 核心模块说明

**`amendment.py`** — 修正案阶段的完整实现

- `build_rules_announcement()`: 构建 5 条规则的广播公告
- `find_top_proposal()`: 从表态中统计最热门的 (规则, 值) 组合
- `amendment_phase()`: 编排完整的 6 步修正案流程

**`structured_model.py`** — 所有数据模型

- `GameConfig`: 5 条规则的 Pydantic 模型，带值域约束
- `StanceModel`: 辩论后的结构化表态（选哪条规则 + 新值）
- `AmendmentVote`: 正式投票（approve: bool）
- `apply_amendment()`: 修正案注入函数（类型转换 + Pydantic 校验）
- 游戏模型：`DiscussionModel`, `get_vote_model()`, `get_poison_model()` 等

**`game.py`** — 配置驱动的狼人杀

- `werewolves_game(agents, config)`: 接收 `GameConfig` 参数
- 5 个配置注入点：最大轮数、狼人讨论轮数、女巫自救、猎人被毒开枪、首夜遗言

**`main.py`** — 入口与编排

- 9 Agent 创建（各自独立性格）
- JSONSession 状态持久化
- Tee 日志系统：终端输出同时写入文件

### 技术栈

- **框架**: [AgentScope](https://github.com/modelscope/agentscope) — ReActAgent / MsgHub / Pipeline
- **模型**: 阿里云 DashScope `qwen3-max`
- **结构化输出**: Pydantic BaseModel + Literal 约束
- **通信模式**: MsgHub 广播 + sequential_pipeline (讨论) + fanout_pipeline (投票)

## 运行日志（logs/）

每次运行游戏，日志会自动保存到 `logs/` 目录，文件名格式为 `game_YYYYMMDD_HHMMSS.log`。

日志完整记录了一局游戏的全过程，包括：

- **修正案阶段**：每个 Agent 的辩论发言、结构化表态、投票结果，以及最终通过或否决的规则修改
- **狼人杀对局**：每一轮的夜晚行动（狼人讨论、女巫决策、预言家查验）和白天讨论、投票放逐的完整对话
- **胜负结果**：最终哪一方获胜，存活玩家列表

通过阅读日志，可以直观观察 AI Agent 的策略行为和博弈过程，是分析"AI 如何改变规则"的第一手材料。

## 设计文档（PRD_and_Text/）

`PRD_and_Text/` 目录保存了项目从调研到实现的完整设计过程文档，共 5 份：

| 文档 | 内容 |
| --- | --- |
| `狼人杀游戏调研.md` | 狼人杀规则调研，梳理了不同版本的规则变体，为选取可修改规则提供依据 |
| `投票制度调研.md` | 议会投票制度调研，为修正案的提案→辩论→投票流程设计提供参考 |
| `AMENDMENT_PHASE.md` | 修正案阶段 6 步流程的详细执行说明，是 `amendment.py` 的施工方案 |
| `CONFIG_INJECTION.md` | GameConfig 中间层设计 + apply_amendment 注入逻辑说明 |
| `GAME_INTEGRATION.md` | 游戏代码 5 个配置注入点的具体改动说明，是 `game.py` 的改造指南 |

这些文档的存在本身也是项目方法论的一部分：**在写代码之前先把需求和设计写清楚**，让 AI 编码时有明确的边界和目标，避免反复返工。

## Roadmap

- [x] 单局游戏：修正案 → 配置注入 → 狼人杀对局
- [ ] **多轮游戏**：上一局的修正案累积到下一局，观察规则的长期演化
- [ ] **深度规则修改**：从修改游戏配置参数，进化到真正修改游戏规则（Prompt 动态注入 / 代码生成）
- [ ] 规则历史与版本追踪
- [ ] 跨局记忆与策略演化分析

## 心路历程

这个项目的开发过程本身就是一次学习：

1. **从调研开始，不要重复造轮子**。我们先调研了狼人杀规则和议会投票制度，找到了成熟的 AgentScope 框架作为基础，而不是从零搭建 Agent 通信和管理系统。站在巨人的肩膀上，AI 搭建成熟框架的能力还比较弱，最终找到一个适用的成熟框架，在此基础上做改造。

2. **跟 AI 聊清楚，Ask and Plan**。在写任何代码之前，先通过反复的对话，交付出能够清晰执行的产品 PRD 和技术执行说明（施工方案图）。这些文档（`PRD_and_Text/` 目录下的 5 份文件）确保了 AI 编码时有明确的目标和边界，避免 token 浪费，事半功倍。

3. **先设计数据结构，再写业务逻辑**。`GameConfig` 作为中间层是整个系统的核心——它既约束了修正案的合法输出，又驱动了游戏代码的行为分支。想清楚数据怎么流动，代码自然就清晰了。

## 致谢

- [AgentScope](https://github.com/modelscope/agentscope) — 提供了优秀的多 Agent 框架和狼人杀示例
- [阿里云 DashScope](https://dashscope.aliyun.com/) — 提供 qwen3-max 模型 API
