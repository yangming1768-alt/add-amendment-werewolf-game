# 修正案阶段 — 执行文档

> Amendment Phase Implementation Spec
> 本文档定义修正案阶段的完整执行流程、数据结构、代码改动点。

> 当前范围说明：本文档当前只覆盖“单局开始前的修正案阶段 + 单局游戏执行”。
> 多轮累积（跨局继承 config、历史记忆注入、连续多局自迭代）暂不纳入当前实现范围，不执行相关设计。

---

## 一、阶段总览

```
┌─ 修正案阶段 ──────────────────────────────────────────────────────┐
│                                                                   │
│  [Step 1] 广播规则                                                 │
│    MsgHub broadcast 5 条规则 + 当前值 + 可选范围                     │
│                                                                   │
│  [Step 2] 3 轮辩论                                                 │
│    auto_broadcast = True                                          │
│    sequential_pipeline(agents) × 3 轮                             │
│    无结构化输出，自由讨论                                             │
│                                                                   │
│  [Step 3] 表态                                                     │
│    auto_broadcast = False                                         │
│    fanout_pipeline + StanceModel                                  │
│    每人输出: {"rule": 3, "value": "true"}                          │
│                                                                   │
│  [Step 4] 统计最热门提案                                             │
│    Counter((rule, value)) → 最热门组合                              │
│    广播: "Rule 3 → true 获得最多支持 (5/9)"                         │
│                                                                   │
│  [Step 5] 正式投票                                                  │
│    fanout_pipeline + AmendmentVote                                │
│    每人输出: {"approve": true/false}                                │
│                                                                   │
│  [Step 6] 判定 + 注入/丢弃                                          │
│    approvals > 4 (过半)?                                           │
│    ├─ 是 → apply_amendment(config, proposal)                      │
│    │       Pydantic 校验通过 → config 更新                          │
│    │       Pydantic 校验失败 → config 不变                          │
│    └─ 否 → config 不变                                             │
│    广播最终结果                                                     │
│                                                                   │
└───────────────────────────────────────────┬───────────────────────┘
                                            │
                                            ▼
                              werewolves_game(agents, config)
```

---

## 二、可配置规则列表（5 条）

| # | 字段名 | 含义 | 默认值 | 可选范围 | 平衡影响 |
|---|--------|------|--------|---------|---------|
| 1 | `max_game_round` | 最大游戏轮数（夜+天循环） | 30 | 10 ~ 50 (int) | 越大微利好人 |
| 2 | `max_werewolf_discussion` | 狼人每夜讨论轮数/每狼 | 3 | 1 ~ 5 (int) | 越大利狼人 |
| 3 | `witch_self_heal` | 女巫能否用解药救自己 | False | true / false | True 利好人 +5~8% |
| 4 | `hunter_on_poison` | 猎人被女巫毒死时能否开枪 | False | true / false | True 利好人 +2~3% |
| 5 | `first_day_last_words` | 第一夜被杀者能否留遗言 | True | true / false | True 利好人 |

---

## 三、数据结构

### 3.1 GameConfig — 规则配置中间层

放在 `structured_model.py` 中。

```python
from pydantic import BaseModel, Field

class GameConfig(BaseModel):
    """Game-level configurable rules / 游戏级可配置规则"""

    max_game_round: int = Field(default=30, ge=10, le=50,
        description="Maximum game rounds / 最大游戏轮数")
    max_werewolf_discussion: int = Field(default=3, ge=1, le=5,
        description="Werewolf discussion rounds per wolf / 每狼讨论轮数")
    witch_self_heal: bool = Field(default=False,
        description="Whether the witch can heal herself / 女巫能否自救")
    hunter_on_poison: bool = Field(default=False,
        description="Whether the hunter can shoot when killed by poison / 猎人被毒能否开枪")
    first_day_last_words: bool = Field(default=True,
        description="Whether the first-night victim can leave last words / 第一夜死者能否遗言")
```

**职责**：
- 存储当前规则状态（每个字段有默认值 = 原始规则）
- 校验修正案合法性（`ge`/`le` 自动拦截越界值）
- 作为参数传递给 `werewolves_game(agents, config)`

### 3.2 StanceModel — 辩论后表态

```python
from typing import Literal

class StanceModel(BaseModel):
    """Agent's stance after debate / 辩论后的表态"""

    rule: Literal[1, 2, 3, 4, 5] = Field(
        description="Which rule number you support changing (1-5)")
    value: str = Field(
        description="The new value you want for this rule. "
                    "For bool rules (3,4,5): 'true' or 'false'. "
                    "For int rules (1,2): a number like '20'.")
```

Agent 输出示例：`{"rule": 3, "value": "true"}`

### 3.3 AmendmentVote — 正式投票

```python
class AmendmentVote(BaseModel):
    """Formal vote on the top amendment / 对最热门修正案的正式投票"""

    approve: bool = Field(
        description="Whether you approve this amendment / 是否赞成该修正案")
```

Agent 输出示例：`{"approve": true}`

### 3.4 AmendmentProposal — 内部传递对象（非 Agent 输出）

```python
class AmendmentProposal(BaseModel):
    """A single rule amendment proposal / 单条规则修正案（内部传递用）"""

    rule: Literal[
        "max_game_round", "max_werewolf_discussion",
        "witch_self_heal", "hunter_on_poison", "first_day_last_words",
    ] = Field(description="Which rule to change / 要修改哪条规则")
    value: str = Field(description="New value for the rule")
    reason: str = Field(description="Why this change / 修改理由")
```

---

## 四、各 Step 详细设计

### Step 1：广播可修改的规则

**目的**：让所有 Agent 知道可以讨论什么、当前值是多少、修改范围是什么。

**实现**：

```python
RULE_NAMES = {
    1: "max_game_round",
    2: "max_werewolf_discussion",
    3: "witch_self_heal",
    4: "hunter_on_poison",
    5: "first_day_last_words",
}

def build_rules_announcement(config: GameConfig) -> str:
    """Build the rules announcement message / 构建规则公告消息"""
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
        f"  Current: {config.witch_self_heal}\n"
        f"  Options: true / false\n\n"

        f"[Rule 4] hunter_on_poison (猎人被毒开枪)\n"
        f"  Meaning: Whether the hunter can still shoot when killed by witch's poison.\n"
        f"  Current: {config.hunter_on_poison}\n"
        f"  Options: true / false\n\n"

        f"[Rule 5] first_day_last_words (第一夜遗言)\n"
        f"  Meaning: Whether the player killed on the first night can leave a final statement.\n"
        f"  Current: {config.first_day_last_words}\n"
        f"  Options: true / false\n\n"

        "You will now debate which rule to change and to what value."
    )
```

**AgentScope 调用**：

```python
async with MsgHub(participants=agents) as amendment_hub:
    await amendment_hub.broadcast(
        await moderator(build_rules_announcement(config)),
    )
```

---

### Step 2：3 轮辩论

**目的**：Agent 们互相交换观点，形成多数意见。

**实现**：
- `auto_broadcast = True`：所有人能看到彼此发言
- `sequential_pipeline`：按顺序发言，后发者能看到前面所有人的发言
- 3 轮 × 9 人 = 27 条消息
- **无结构化输出**：自由讨论，和游戏内白天讨论同一模式

```python
    # 辩论阶段 / Debate phase
    amendment_hub.set_auto_broadcast(True)
    await amendment_hub.broadcast(
        await moderator(
            "Now debate which rule to change. You have 3 rounds to discuss. "
            "State which rule you support changing, the new value, and your reason."
        ),
    )
    for _round in range(3):
        await sequential_pipeline(agents)
    amendment_hub.set_auto_broadcast(False)
```

**Agent 发言样例**（无格式约束）：

> "I think we should change Rule 3 (witch_self_heal) to True. Last game
> the witch was killed on night 1 and couldn't do anything."

---

### Step 3：表态

**目的**：结构化收集每个 Agent 最终支持的 (规则, 值) 组合。

**实现**：
- `auto_broadcast = False`：互不可见，独立表态
- `fanout_pipeline`：并行独立输出
- `structured_model = StanceModel`：Pydantic 约束输出格式

```python
    # 表态阶段 / Stance phase
    stance_msgs = await fanout_pipeline(
        agents,
        msg=await moderator(
            "Debate is over. Now state your position: which ONE rule do you want "
            "to change, and to what value?"
        ),
        structured_model=StanceModel,
        enable_gather=False,
    )
```

**Agent 输出**（JSON）：

```json
{"rule": 3, "value": "true"}
```

---

### Step 4：统计最热门提案

**目的**：找出 (rule, value) 组合中得票最多的，作为唯一进入正式投票的提案。

**实现**：

```python
from collections import Counter

def find_top_proposal(stance_msgs: list) -> tuple[int, str, int]:
    """Find the most popular (rule, value) combo / 找到最热门的 (规则, 值) 组合

    Returns:
        (rule_number, value_str, vote_count)
    """
    combos = []
    for msg in stance_msgs:
        rule = msg.metadata.get("rule")
        value = msg.metadata.get("value")
        combos.append((rule, str(value)))

    counter = Counter(combos)
    (top_rule, top_value), top_count = counter.most_common(1)[0]
    return top_rule, top_value, top_count
```

**广播统计结果**：

```python
    top_rule, top_value, top_count = find_top_proposal(stance_msgs)

    await amendment_hub.broadcast(
        await moderator(
            f"Stance results: Rule {top_rule} ({RULE_NAMES[top_rule]}) → {top_value} "
            f"received the most support ({top_count}/9 stances). "
            f"Now entering formal vote on this amendment."
        ),
    )
```

**样例广播**：

```
Stance results: Rule 3 (witch_self_heal) → true received the most support
(5/9 stances). Now entering formal vote on this amendment.
```

---

### Step 5：正式投票

**目的**：对最热门提案做二选一投票（赞成/反对），独立投票不互相影响。

**实现**：

```python
    # 正式投票 / Formal vote
    vote_msgs = await fanout_pipeline(
        agents,
        msg=await moderator(
            f"FORMAL VOTE: Change Rule {top_rule} ({RULE_NAMES[top_rule]}) "
            f"from {getattr(config, RULE_NAMES[top_rule])} to {top_value}. "
            f"Do you approve this amendment?"
        ),
        structured_model=AmendmentVote,
        enable_gather=False,
    )
```

**Agent 输出**（JSON）：

```json
{"approve": true}
```

---

### Step 6：判定 + 注入/丢弃

**目的**：统计赞成票，过半则通过并应用到 GameConfig，否则丢弃。

**实现**：

```python
    # 统计赞成票 / Count approvals
    approvals = sum(1 for msg in vote_msgs if msg.metadata.get("approve"))
    total = len(agents)  # 9
    passed = approvals > total / 2  # > 4.5，即 >= 5

    if passed:
        proposal = AmendmentProposal(
            rule=RULE_NAMES[top_rule],
            value=top_value,
            reason=f"Passed by vote {approvals}/{total}",
        )
        try:
            config = apply_amendment(config, proposal)
            result_msg = (
                f"Amendment PASSED ({approvals}/{total}): "
                f"{RULE_NAMES[top_rule]} changed to {top_value}."
            )
        except ValidationError as e:
            result_msg = (
                f"Amendment passed vote but REJECTED by validation: {e}"
            )
    else:
        result_msg = (
            f"Amendment REJECTED ({approvals}/{total}, needed >{total//2}): "
            f"{RULE_NAMES[top_rule]} stays at "
            f"{getattr(config, RULE_NAMES[top_rule])}."
        )

    await amendment_hub.broadcast(await moderator(result_msg))
```

---

## 五、设计约束

1. **每轮最多通过 1 条修正案** — 符合议会制度（每次只表决一个议案）
2. **投票门槛 > 50%**（5 条规则都是同一门槛）— 简化实现，后续可按规则类型分层
3. **表态与正式投票分离** — 先聚合观点，再对单一提案做正式表决，避免同时表决多个议题
4. **当前仅做单局方案** — 不要求实现跨局 config 累积、历史规则继承和外层多轮调度
5. **配置注入和主流程调用单独说明** — 相关内容拆分到独立执行文档，避免本文件职责过宽
