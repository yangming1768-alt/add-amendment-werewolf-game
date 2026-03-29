# AI 自迭代狼人杀 — Copilot 工作空间指引

## 项目概述
基于 AgentScope 的 AI 自迭代狼人杀游戏。9 个 AI Agent 在完成标准狼人杀游戏后，可以集体提案、辩论和投票修改游戏规则，修改后的规则注入下一局游戏，形成"规则自进化"的闭环。

## 技术栈
- **运行时**: Python 3.12+, asyncio
- **框架**: AgentScope (ReActAgent, MsgHub, Pipeline, JSONSession)
- **模型**: DashScope (qwen3-max), 需 `DASHSCOPE_API_KEY` 环境变量
- **结构化输出**: Pydantic BaseModel + Literal 约束

## 项目结构
```
werewolf_game/       # 核心游戏实现
  game.py            # 游戏主循环: 夜晚→白天→胜负判定
  main.py            # 入口: 9 Agent 创建 + JSONSession 持久化
  prompt.py          # 中英双语提示词模板 (EnglishPrompts / ChinesePrompts)
  structured_model.py # Pydantic 结构化输出模型 (VoteModel, WitchPoisonModel 等)
  utils.py           # Players 状态管理, majority_vote(), EchoAgent(主持人)
agentscope_debate/   # AgentScope 辩论参考示例
PRD_and_Text/        # 设计文档与调研
  DESIGN.md          # 产品框架设计 (核心参考)
  投票制度调研.md      # 世界议会投票制度调研
  狼人杀游戏调研.md    # 狼人杀游戏规则调研
```

## 核心设计模式
- **MsgHub 嵌套**: 全体广播 hub 内嵌狼人私聊 hub，`auto_broadcast` 动态切换可见性
- **Pipeline 分工**: `sequential_pipeline` 用于讨论（有序）, `fanout_pipeline` 用于投票（并行独立）
- **结构化约束**: Pydantic `Literal[tuple(agent_names)]` 确保投票只能选合法目标
- **状态持久化**: `JSONSession` 保存/加载 Agent 状态，支持跨局记忆

## 运行方式
```bash
cd werewolf_game/
# 设置 API Key
$env:DASHSCOPE_API_KEY = "your_key"
python main.py
```

## 当前核心任务: 修正案注入系统
项目处于设计阶段，核心挑战是实现 **提案→辩论→投票→规则注入→游戏执行** 闭环。
- **方案 A (JSON 配置修改)**: 修改数值参数 (狼人数量、女巫自救等)，Pydantic 约束合法值
- **方案 B (Prompt 动态注入)**: 自然语言规则变更注入 Agent sys_prompt，高自由度但低确定性
- **混合方案**: 基础参数用 A，行为规则用 B
- 详见 [PRD_and_Text/DESIGN.md](PRD_and_Text/DESIGN.md)

## 编码约定
- 所有代码双语注释 (英文优先 + 中文注释)
- async/await 贯穿全局，不使用同步阻塞
- 新 Pydantic 模型放 `structured_model.py`，新提示词放 `prompt.py`
- Agent 交互通过 `MsgHub` + `Pipeline`，不直接调用 `agent.reply()`
