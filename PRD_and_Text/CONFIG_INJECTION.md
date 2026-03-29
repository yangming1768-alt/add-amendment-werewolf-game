# 配置层注入 — 执行说明

> Configuration Injection Spec
> 本文档定义修正案通过后，如何将结构化结果安全注入到 GameConfig，并让游戏规则层读取生效。

---

## 一、职责边界

配置层只负责三件事：

1. 接收修正案阶段产出的最终提案。
2. 将提案里的字符串值转换为 GameConfig 字段的真实类型。
3. 用 Pydantic 校验并生成新的 GameConfig。

配置层**不负责**：
- Agent 辩论
- 票数统计
- 游戏阶段执行
- 跨局累积

---

## 二、输入输出

### 输入

配置层接收两个输入：

1. 当前配置 `config: GameConfig`
2. 通过正式投票的提案 `proposal: AmendmentProposal`

```python
class AmendmentProposal(BaseModel):
    rule: Literal[
        "max_game_round",
        "max_werewolf_discussion",
        "witch_self_heal",
        "hunter_on_poison",
        "first_day_last_words",
    ]
    value: str
    reason: str
```

输入示例：

```python
config = GameConfig(
    max_game_round=30,
    max_werewolf_discussion=3,
    witch_self_heal=False,
    hunter_on_poison=False,
    first_day_last_words=True,
)

proposal = AmendmentProposal(
    rule="witch_self_heal",
    value="true",
    reason="Passed by vote 5/9",
)
```

### 输出

输出是一个新的 `GameConfig`：

```python
GameConfig(
    max_game_round=30,
    max_werewolf_discussion=3,
    witch_self_heal=True,
    hunter_on_poison=False,
    first_day_last_words=True,
)
```

如果值不合法，则抛出 `ValidationError`，调用方决定是否丢弃该提案。

---

## 三、GameConfig 定义

```python
from pydantic import BaseModel, Field

class GameConfig(BaseModel):
    """Game-level configurable rules / 游戏级可配置规则"""

    max_game_round: int = Field(default=30, ge=10, le=50)
    max_werewolf_discussion: int = Field(default=3, ge=1, le=5)
    witch_self_heal: bool = Field(default=False)
    hunter_on_poison: bool = Field(default=False)
    first_day_last_words: bool = Field(default=True)
```

### 字段说明

| 字段 | 类型 | 默认值 | 校验 |
|------|------|--------|------|
| `max_game_round` | `int` | 30 | `10 <= value <= 50` |
| `max_werewolf_discussion` | `int` | 3 | `1 <= value <= 5` |
| `witch_self_heal` | `bool` | False | 只接受布尔语义 |
| `hunter_on_poison` | `bool` | False | 只接受布尔语义 |
| `first_day_last_words` | `bool` | True | 只接受布尔语义 |

---

## 四、核心函数：apply_amendment

```python
from pydantic import ValidationError


def apply_amendment(config: GameConfig, proposal: AmendmentProposal) -> GameConfig:
    """Apply a passed amendment to the current config.
    将通过的修正案应用到当前配置。

    Args:
        config: Current game config / 当前游戏配置
        proposal: The passed amendment / 投票通过的修正案

    Returns:
        A new validated GameConfig / 新的、已校验的配置对象

    Raises:
        ValidationError: If the new value is invalid / 新值不合法时抛异常
    """
    current = config.model_dump()

    field_info = GameConfig.model_fields[proposal.rule]
    field_type = field_info.annotation

    if field_type is bool:
        new_value = proposal.value.lower() in ("true", "1", "yes")
    elif field_type is int:
        new_value = int(proposal.value)
    else:
        new_value = proposal.value

    current[proposal.rule] = new_value
    return GameConfig(**current)
```

---

## 五、执行时序

### Step 1：复制当前配置

```python
current = config.model_dump()
```

作用：
- 把 Pydantic 对象转成普通字典。
- 后续修改发生在字典上，不直接原地改 `config`。
- 如果新值非法，原 config 仍保持不变。

示例：

```python
current = {
    "max_game_round": 30,
    "max_werewolf_discussion": 3,
    "witch_self_heal": False,
    "hunter_on_poison": False,
    "first_day_last_words": True,
}
```

### Step 2：定位目标字段

```python
field_info = GameConfig.model_fields[proposal.rule]
field_type = field_info.annotation
```

作用：
- 通过 `proposal.rule` 查出要修改的是哪个字段。
- 再读取该字段声明的目标类型。

示例：

```python
proposal.rule == "witch_self_heal"
field_type == bool
```

### Step 3：类型转换

因为 Agent 输出的 `value` 统一是字符串，所以要先转型。

#### 布尔字段

```python
new_value = proposal.value.lower() in ("true", "1", "yes")
```

示例：

| 输入字符串 | 结果 |
|-----------|------|
| `"true"` | `True` |
| `"True"` | `True` |
| `"yes"` | `True` |
| `"1"` | `True` |
| `"false"` | `False` |
| `"0"` | `False` |

#### 整数字段

```python
new_value = int(proposal.value)
```

示例：

| 输入字符串 | 结果 |
|-----------|------|
| `"20"` | `20` |
| `"5"` | `5` |
| `"abc"` | `ValueError` |

### Step 4：写入候选配置

```python
current[proposal.rule] = new_value
```

示例：

```python
current["witch_self_heal"] = True
```

写入后：

```python
current = {
    "max_game_round": 30,
    "max_werewolf_discussion": 3,
    "witch_self_heal": True,
    "hunter_on_poison": False,
    "first_day_last_words": True,
}
```

### Step 5：Pydantic 校验并构造新配置

```python
return GameConfig(**current)
```

作用：
- 将字典重新组装成 Pydantic 对象。
- 自动执行所有字段校验。
- 如果值不合法，立即抛 `ValidationError`。

示例：

```python
GameConfig(**{
    "max_game_round": 999,
    ...
})
```

会失败，因为 `999 > 50`。

---

## 六、成功路径与失败路径

### 成功路径

```
proposal = (rule="witch_self_heal", value="true")
    ↓
类型转换: "true" → True
    ↓
写入 current["witch_self_heal"] = True
    ↓
GameConfig(**current) 校验通过
    ↓
返回新 config
```

### 失败路径 A：值格式错误

```
proposal = (rule="max_game_round", value="abc")
    ↓
int("abc")
    ↓
ValueError
    ↓
调用方捕获并丢弃该提案
```

### 失败路径 B：值越界

```
proposal = (rule="max_game_round", value="999")
    ↓
int("999") → 999
    ↓
GameConfig(**current)
    ↓
ValidationError (超过 le=50)
    ↓
调用方捕获并丢弃该提案
```

---

## 七、调用方如何使用

配置层通常在修正案阶段最后调用：

```python
approvals = sum(1 for msg in vote_msgs if msg.metadata.get("approve"))
passed = approvals > len(agents) / 2

if passed:
    proposal = AmendmentProposal(
        rule=RULE_NAMES[top_rule],
        value=top_value,
        reason=f"Passed by vote {approvals}/{len(agents)}",
    )
    try:
        config = apply_amendment(config, proposal)
        result_msg = f"Amendment PASSED: {proposal.rule} -> {proposal.value}"
    except (ValidationError, ValueError) as e:
        result_msg = f"Amendment rejected by config validation: {e}"
else:
    result_msg = "Amendment failed formal vote."
```

注意：
- 建议调用方同时捕获 `ValidationError` 和 `ValueError`。
- `ValidationError` 是 Pydantic 越界校验失败。
- `ValueError` 常见于 `int("abc")` 这种类型转换失败。

---

## 八、当前范围说明

当前版本配置层只处理**单局运行前的一次配置更新**：

```python
config = GameConfig()
config = await amendment_phase(players, config)
await werewolves_game(players, config)
```

当前不执行：
- 跨局累积 config
- 规则历史 diff
- 版本回滚
- 配置快照持久化

---

## 九、与其他文档的关系

- 修正案阶段流程见 `AMENDMENT_PHASE.md`
- 游戏主流程接入见 `GAME_INTEGRATION.md`

本文件只回答一个问题：

**“正式投票通过后，修正案如何安全变成 GameConfig？”**
