---
created: 2026-09-30
tags: [AI与大模型测试/LLM评测]
---

# 大语言模型（LLM）自动化评测体系与指标

> 解决大模型生成式 AI 输出具有「开放性与非确定性」，无法通过传统字面等值或正则进行断言的自动化评测体系与方法论。

## 概念

在传统接口自动化测试中，输入 $A$ 必然得到确定性的输出 $B$，断言逻辑通常是 `assert response.json()["status"] == 200` 或字段完全匹配。但在大语言模型（LLM）落地场景中，即使给定完全相同的 Prompt，由于采样参数（Temperature、Top_p）以及自回归生成的概率特性，输出也是开放多样、语义相同但字面不同的非确定性文本。

### 评测指标与技术演进

```text
               ┌────────────────────────────────────────────────────────┐
               │ 阶段 1：字面匹配（传统 NLP）                             │
               │ 指标：BLEU, ROUGE-1/2/L, Exact Match (EM)               │
               │ 局限：只看 n-gram 词重合，无法识别同义词与语序重组       │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │ 阶段 2：语义嵌入相似度（Embedding-based）                │
               │ 指标：BERTScore, 余弦相似度 (Cosine Similarity)         │
               │ 局限：缺乏逻辑推理能力，能测相关性但无法测事实真伪       │
               └───────────────────────────┬────────────────────────────┘
                                           │
                                           ▼
               ┌────────────────────────────────────────────────────────┐
               │ 阶段 3：大模型裁判（LLM-as-a-Judge）                     │
               │ 机制：使用业界顶尖推理模型（如 GPT-4/Claude 3.5/DeepSeek）│
               │ 模式：单点评分（Direct Scoring）、两两对决（Pairwise）  │
               │ 优势：理解上下文逻辑、事实一致性、复杂指令遵从度         │
               └────────────────────────────────────────────────────────┘
```

---

## 用法

### 1. LLM-as-a-Judge 自动化评测流水线

在自动化评测用例中，评测框架通过标准化 Prompt 要求强裁判模型给出明确评分（1~5 分）及 JSON 格式判词，并通过**双向调换位置（Position Swapping）**消除位置偏见：

```python
import json
from typing import Dict, Any
from openai import OpenAI

client = OpenAI(api_key="your-api-key")

JUDGE_PROMPT_TEMPLATE = """
你是一名极其严格的 AI 输出质量评估专家。请根据提供的用户输入（Prompt）和标准参考事实（Ground Truth），对被测模型生成的回答（Model Output）进行多维度评测。

[评测维度]:
1. 准确性（Accuracy）：回答是否符合客观事实，有无虚构幻觉；
2. 指令遵从（Instruction Following）：是否严格执行了格式、字数、语种等约束；
3. 逻辑连贯性（Coherence）：逻辑是否清晰，表达是否通顺。

[输入数据]:
- 用户提问: {query}
- 标准参考: {reference}
- 被测模型回答: {candidate}

请严格按以下 JSON 格式输出，不要附加任何其他 Markdown 或解释：
{{
  "accuracy_score": 1-5,
  "instruction_score": 1-5,
  "coherence_score": 1-5,
  "total_score": 1-5,
  "reasoning": "扣分或给分的具体依据"
}}
"""

def evaluate_single_response(query: str, reference: str, candidate: str) -> Dict[str, Any]:
    """使用 LLM-as-a-Judge 进行自动化质量打分"""
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        query=query,
        reference=reference,
        candidate=candidate
    )
    
    response = client.chat.completions.create(
        model="gpt-4o",  # 必须使用推理能力强于被测模型的顶尖模型作为 Judge
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0, # 评测阶段将温度归零，保证打分稳定性
        response_format={"type": "json_object"}
    )
    
    result = json.loads(response.choices[0].message.content)
    return result

# 自动化测试用例示例
def test_customer_service_bot_accuracy():
    user_query = "你们退货政策是几天内？运费谁承担？"
    ground_truth = "签收后7天内支持无理由退货。质量问题商家承担运费，非质量问题买家自理。"
    
    # 模拟被测服务输出
    actual_model_output = "您好，我们支持7天退货，如果是商品损坏由我们出运费，个人原因退货运费需自行承担哦。"
    
    eval_result = evaluate_single_response(user_query, ground_truth, actual_model_output)
    print(f"评测得分: {eval_result['total_score']}, 原因: {eval_result['reasoning']}")
    
    # 断言门禁：综合得分必须大于等于 4 分，且无事实性幻觉
    assert eval_result["total_score"] >= 4
    assert eval_result["accuracy_score"] >= 4
```

---

## 踩坑

1. **位置偏见（Position Bias）**：
   - 在进行 A/B 两个模型两两对决盲测（Pairwise）时，裁判模型更倾向于判定排在第一个（Model A）或者排在第二个（Model B）的模型获胜。
   - **解法**：必须进行**双向互换测试（Swap Position）**。每次评测同时运行 `(A, B)` 和 `(B, A)`，只有两次评测结果判定同一模型获胜时才计入胜场，若出现冲突则记为平局（Tie）。
2. **冗长偏见（Verbosity Bias）**：
   - 评测模型天然倾向于给“字数更多、排版更丰富、列表更繁琐”的回答打高分，哪怕其中充斥着大量无关的车轱辘废话。
   - **解法**：在 Judge Prompt 中明确加入负向约束：*“不要因为回答更长或包含更多无关客套而给予高分，冗余和答非所问必须扣分”*；或将输出长度纳入字数惩罚因子。
3. **自恋偏见（Self-Enhancement Bias）**：
   - 当使用 GPT-4 评测 GPT-4 与 Claude-3.5 的回答时，GPT-4 会潜意识里觉得带有 OpenAI 风格用词的输出更加得体。
   - **解法**：核心评测基准应当引入**双裁判机制**（例如：Claude 与 GPT 交叉双重评测）或对两者分歧用例由人工标注团队（Human-in-the-loop）裁决。

---

## 面试怎么答

> **面试官会怎么问**：
> 大模型生成的内容每次都不一样，你们自动化测试怎么做质量断言？怎么证明新版模型的效果优于旧版？

**30 秒回答骨架**：
> “我们建立了**自动化基准回归集 + LLM-as-a-Judge** 的全套评测流水线。首先，摒弃传统的精确字符比对，针对非创造性场景使用语义 Embedding 计算余弦相似度；针对复杂多轮对话与逻辑任务，搭建以 GPT-4o / DeepSeek-V3 为裁判的评测脚本。通过零温度（Temperature=0）、结构化 JSON Prompt 输出准确性、相关性、遵从度等 5 个维度的打分。为了消除位置偏差和冗长偏差，我们实行**双向盲测（Swap Position）与字数惩罚**，从而在模型微调或迭代发布前产出客观量化的胜率矩阵和通过率门禁。”

**容易被追问的点**：
- **追问**：用大模型评测大模型，如何确保裁判模型自己的评分是靠谱的？
  - *回答要点*：评测上线前必须进行**人机一致性校准（Human Alignment Check）**。由算法与资深测试工程师手工标注 200~500 条样本的黄金评分，让 Judge 模型跑相同样本，计算 Cohen's Kappa 系数或皮尔逊相关系数（Pearson Correlation）。当相关性达到 0.85 以上时，才证明此套 Judge Prompt 具有在 CI 流水线中无人值守执行的置信度。

---

## 参考

- [[15-AI与大模型测试]] —— 模块主入口
- [[RAG 检索增强生成系统质量评测（RAGAS 实战）]] —— RAG 专项评测
- [[AI Agent 智能体工具调用与规划稳定性评测]] —— 智能体评测
- [[06-接口自动化测试]] —— 传统接口自动化对比
