---
created: 2026-09-30
tags: [AI与大模型测试/Agent评测]
---

# AI Agent 智能体工具调用与规划稳定性评测

> 针对具备多步推理（ReAct）、外部工具调用（Tool Calling / Function Calling）与环境交互能力的 AI Agent 系统的稳定性与有效性评测。

## 概念

传统的单轮大模型问答属于**无状态的“文本进、文本出”**；而 **AI Agent（智能体）** 具备自主规划目标、拆解步骤、调用外部 API（查询数据库、发送邮件、调用计算器）、观察工具返回结果并动态调整决策的闭环能力：

$$\text{Thought（思考）} \to \text{Action（行动/调用工具）} \to \text{Observation（观察环境返回）} \to \text{Finish（终止或继续）}$$

在 Agent 系统中，评测重点不再只是最终文案的美观度，而是**整条决策链路（Trajectory）的正确性与系统稳定性**。

### Agent 自动化评测的核心维度

```text
               ┌────────────────────────────────────────────────────────┐
               │ 1. 工具选择准确率（Tool Selection Accuracy）           │
               │ 给定任务，是否准确选择了应该调用的 Tool，无误调用与漏调用│
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │ 2. 参数遵从度（Parameter Compliance）                   │
               │ 生成的 JSON 参数类型、必填字段、格式是否符合 OpenAPI 契约│
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │ 3. 规划轨迹正确性（Trajectory & Step Efficiency）        │
               │ 是否有多余的冗余调用？能否在有限步数内达成目标？       │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │ 4. 容错与反思鲁棒性（Error Handling & Reflection）      │
               │ 当工具抛出 404 / 500 或入参报错时，能否自我修正而非死循环 │
               └────────────────────────────────────────────────────────┘
```

---

## 用法

### 1. 使用 Mock 环境评测 Agent 的 Tool Calling 轨迹

在自动化测试中，不能直接让 Agent 连接真实的线上数据库或真实发送短信，必须**构建可注入受控返回值的 Mock Tool 桩**，并录制追踪 Agent 的每一步 `tool_calls`。

```python
import json
import pytest
from typing import List, Dict, Any

# 1. 模拟被测系统暴露给 Agent 的两个 OpenAPI 描述规范
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "query_flight_tickets",
            "description": "查询指定城市之间的航班机票",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "出发地"},
                    "destination": {"type": "string", "description": "目的地"},
                    "date": {"type": "string", "description": "出发日期 YYYY-MM-DD"}
                },
                "required": ["origin", "destination", "date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_flight_ticket",
            "description": "预订指定航班",
            "parameters": {
                "type": "object",
                "properties": {
                    "flight_no": {"type": "string", "description": "航班号"},
                    "passenger_name": {"type": "string", "description": "乘机人姓名"}
                },
                "required": ["flight_no", "passenger_name"]
            }
        }
    }
]

# 2. 轨迹断言助手类
class TrajectoryRecorder:
    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def record_call(self, tool_name: str, arguments: dict):
        self.calls.append({"tool": tool_name, "args": arguments})

def test_agent_two_step_booking_trajectory():
    """
    测试用例：
    用户需求：“帮张三订一张明天从北京到上海的机票”
    断言目标：
    1. Agent 第一步必须先调用 query_flight_tickets 查询有效航班；
    2. Agent 不允许在未查询到任何航班时直接猜一个航班号调用 book_flight_ticket；
    3. 最大步数不能超过 5 步，杜绝无限递归死循环。
    """
    recorder = TrajectoryRecorder()
    
    # 模拟 Agent 在 ReAct 循环中的执行链路（通常对接真实大模型 API 驱动）
    # 模拟步骤 1：思考后决策查询
    step_1_tool = "query_flight_tickets"
    step_1_args = {"origin": "北京", "destination": "上海", "date": "2026-10-01"}
    recorder.record_call(step_1_tool, step_1_args)
    
    # 模拟环境反馈
    mock_env_response = json.dumps([{"flight_no": "CA1234", "price": 850}])
    
    # 模拟步骤 2：获取返回后决策下单
    step_2_tool = "book_flight_ticket"
    step_2_args = {"flight_no": "CA1234", "passenger_name": "张三"}
    recorder.record_call(step_2_tool, step_2_args)
    
    # ======== 自动化评测断言 ========
    # 断言 1：总交互步数受控
    assert len(recorder.calls) == 2, f"规划步数异常，预期 2 步，实际 {len(recorder.calls)} 步"
    
    # 断言 2：工具调用的顺序正确性
    assert recorder.calls[0]["tool"] == "query_flight_tickets"
    assert recorder.calls[0]["args"]["origin"] == "北京"
    assert recorder.calls[0]["args"]["destination"] == "上海"
    
    assert recorder.calls[1]["tool"] == "book_flight_ticket"
    assert recorder.calls[1]["args"]["flight_no"] == "CA1234"
    assert recorder.calls[1]["args"]["passenger_name"] == "张三"
```

---

## 踩坑

1. **死循环死锁（Agent Infinite Loop）**：
   - 当某个工具返回了空结果（如 `[]`）或报错字符串时，部分大模型会持续使用相同的参数不断重试调用该工具数十次，耗尽 Token 乃至让被测服务宕机。
   - **解法**：系统必须具备**硬性最大步数限制（Max Iterations Guard，如设为 8 步）**与**重复动作探测器（Action Repetition Detector）**。当检测到相同工具与相同参数连续出现 2 次时，强行中断执行并向用户提示无法完成。
2. **幻觉修改参数契约（Schema Drift）**：
   - 工具定义的是 `flight_no`，大模型偶尔自作主张传递成 `flight_number` 或 `flightId`，导致下游接口反序列化失败直接报 422 错误。
   - **解法**：在 Agent 的输出解析层（Parser）增加 **Pydantic 运行时严格校验与重试纠错机制（Self-Correction）**。一旦解析报错，将错误信息作为 Observation 返还给模型，促其立刻自我纠错。

---

## 面试怎么答

> **面试官会怎么问**：
> 你们是怎么测试 AI Agent（智能体）的？它和普通的 Prompt 测试有什么区别？

**30 秒回答骨架**：
> “测试 Agent 的核心是从**‘测试单次生成’升级为‘测试整条交互轨迹（Trajectory）’**。我们重点考核三个指标：
> 1. **工具调用准确率（Tool Accuracy）**：入参格式、必填字段是否完全契合 OpenAPI Schema，有无参数幻觉；
> 2. **执行路径效率（Step Efficiency）**：完成既定业务目标的执行步数是否最优，有无多余无意义动作；
> 3. **异常反思与鲁棒性（Self-Correction）**：当外部 Mock 故意返回 500、超时或空数据时，Agent 是否会陷入死循环，能否主动向用户解释阻断原因。
> 我们通过沙箱 Mock 环境隔离外部依赖，基于预定义的 Golden Trajectories 实现了 Agent 的全自动回归门禁。”

---

## 参考

- [[15-AI与大模型测试]] —— 大模型评测 MOC
- [[大语言模型（LLM）自动化评测体系与指标]] —— 评测基准
- [[06-接口自动化测试]] —— 接口与契约测试
