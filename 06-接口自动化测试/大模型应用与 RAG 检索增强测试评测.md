---
created: 2026-09-28
tags: [接口自动化测试/大模型评测]
---

# 大模型应用与 RAG 检索增强测试评测

> 解决生成式 AI 接口输出不确定性、幻觉、RAG 检索召回不准及基于 LLM-as-a-Judge 的质量门禁量化评测体系。

## 概念

### 1. 为什么传统确定性断言在大模型上彻底失效

传统的接口自动化测试核心依赖确定性判定：
```python
# 传统断言：期待完全相等、正则匹配或 JSON Schema 校验
assert response.status_code == 200
assert response.json()["data"]["reply"] == "北京是中国的首都。"
```
但在大语言模型（LLM）及智能体应用中：
- **概率生成机理**：即使 `temperature=0`，在浮点精度与并发推理环境下，模型表达方式依然具备多变性（如“中国的首都是北京”、“北京为中华人民共和国首都”）。
- **非结构化自然语言**：直接用 `==`、`in` 或正则表达式极易发生误判（False Negative）或遗漏虚假回答（False Positive）。
- **必须演进为统计与语义评测**：引入语义相似度（Embedding Cosine Similarity）、规则启发式过滤与 **LLM-as-a-Judge（大模型作为裁判）**。

### 2. RAG 核心链路测试痛点

RAG（Retrieval-Augmented Generation，检索增强生成）系统包含两大关键阶段：
1. **检索阶段（Retrieval）**：User Query -> Embedding -> 向量数据库 / 混合检索 -> Top-K 文本块（Contexts）。
2. **生成阶段（Generation）**：System Prompt + Top-K Contexts + User Query -> LLM -> Answer。

测试不仅要测最终 Answer 的好坏，必须**切片归因**：答案错误究竟是“检索没捞上来”（Retrieval 缺陷），还是“检索到了但大模型理解错了或生成了幻觉”（Generation 缺陷）。

### 3. Ragas 四维核心黄金指标

工业界主流评测框架（如 Ragas）定义的 RAG 三元组与四维评估指标：

```text
               ┌─────────────┐
               │    Query    │
               └──────┬──────┘
         ┌────────────┴────────────┐
         │ (Context Relevance)     │ (Answer Relevance)
         ▼                         ▼
┌─────────────────┐       ┌─────────────────┐
│ Context (检索召回)│──────>│ Answer (最终回答)│
└─────────────────┘       └─────────────────┘
         │                         ▲
         └─────────────────────────┘
                 (Faithfulness)
```

1. **Faithfulness（忠实度 / 真实性）**：Answer 中陈述的每个事实能否直接从检索到的 Context 中推导出来？（度量模型是否产生无中生有的幻觉）。
2. **Answer Relevance（答案相关性）**：Answer 是否切中 Query 的核心意图？（度量回答是否跑题或啰嗦冗余）。
3. **Context Precision（上下文精确率）**：检索回来的 Top-K 文本块中，与 Ground Truth 相关的优质块是否排在前面？（度量重排序 Rerank 质量）。
4. **Context Recall（上下文召回率）**：Ground Truth 中的关键事实是否被检索到的 Context 完整覆盖？（度量向量库召回切分策略）。

---

## 用法

### 1. 使用 Ragas 自动化评测 RAG 流水线

安装评估依赖：
```bash
pip install ragas datasets langchain-openai pytest
```

编写针对 RAG 系统的离线黄金测试集评估用例：

```python
import pytest
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevance,
    context_precision,
    context_recall,
)


@pytest.fixture(scope="session")
def rag_golden_dataset():
    """准备评测测试集（含用户问题、系统召回的上下文、模型生成的回复、标准答案）"""
    data = {
        "question": [
            "公司年假未休完如何折算工资？",
            "如何在测试平台申请一台专属执行机？"
        ],
        "contexts": [
            [
                "员工当年度未休年假，公司应按照日工资收入的 300% 支付年休假报酬，其中包含用人单位支付正常工作期间的工资收入。",
                "每年 12 月 31 日 HR 系统将统一发起年假清零与折算核算。"
            ],
            [
                "点击资产中心 -> 申请节点 -> 选择执行机规格 -> 提交主管审批。",
                "审批通过后，DevOps 平台将在 10 分钟内自动通过 Terraform 交付 VM。"
            ]
        ],
        "answer": [
            "年假未休完会按照日工资的 300% 折算报酬发放，12 月底 HR 统一处理。",
            "直接去机器房找运维领一台即可。"  # 故意构造的幻觉/错误答案
        ],
        "ground_truth": [
            "按照日工资收入的 300% 支付报酬，并在 12 月底统一结算。",
            "在资产中心提交规格申请，主管审批通过后系统自动交付。"
        ]
    }
    return Dataset.from_dict(data)


def test_rag_pipeline_quality_gate(rag_golden_dataset):
    """流水线质量门禁断言"""
    # 评测指定指标
    results = evaluate(
        dataset=rag_golden_dataset,
        metrics=[
            faithfulness,
            answer_relevance,
            context_precision,
            context_recall,
        ]
    )

    df = results.to_pandas()
    print("\n=== RAG Evaluation Report ===")
    print(df[["question", "faithfulness", "answer_relevance", "context_recall"]])

    # 门禁阈值卡控（例如整体忠实度 > 0.85，召回率 > 0.80）
    assert results["faithfulness"] >= 0.80, f"Faithfulness below threshold: {results['faithfulness']}"
    assert results["context_recall"] >= 0.75, f"Context recall below threshold: {results['context_recall']}"
```

### 2. LLM-as-a-Judge 自定义判定器实现

在轻量级接口自动化中，可以直接使用高阶裁判模型（如 GPT-4o、Claude 3.5 Sonnet）实现结构化判分：

```python
import json
from openai import OpenAI

client = OpenAI()

JUDGE_PROMPT_TEMPLATE = """你是一个严谨的 AI 输出质量评估专家。请评估以下模型回答是否严格遵循了参考资料。

[参考上下文]:
{context}

[用户提问]:
{query}

[待评测模型回答]:
{answer}

请按照以下规则打分（0-5分）：
- 5分：回答完全正确，忠实于参考资料，无任何幻觉或答非所问。
- 3分：回答基本正确，但包含参考资料中未提及的细微外推。
- 1分：回答存在严重事实性错误或严重跑题。

输出必须为纯 JSON 格式：
{{"score": 整数, "reasoning": "评判理由"}}
"""


def evaluate_with_llm_judge(context: str, query: str, answer: str) -> dict:
    prompt = JUDGE_PROMPT_TEMPLATE.format(context=context, query=query, answer=answer)
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.0,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


def test_single_turn_judge():
    ctx = "pytest 是一款强大的 Python 测试框架，支持参数化和 fixture。"
    q = "pytest 支持哪些特性？"
    a = "pytest 支持参数化测试和 fixture 依赖注入。"

    result = evaluate_with_llm_judge(ctx, q, a)
    assert result["score"] >= 4, f"Judge failed: {result['reasoning']}"
```

### 3. Promptfoo CLI 快速批量对比回归

在 CI 中对 Prompt 或模型版本变更做自动化回归比对（`promptfooconfig.yaml`）：

```yaml
# promptfooconfig.yaml
prompts:
  - "你是一名专业客服，请基于上下文礼貌回答：{{context}}\n用户：{{query}}"

providers:
  - openai:gpt-4o-mini
  - anthropic:claude-3-5-sonnet-20241022

tests:
  - vars:
      query: "能退货吗？"
      context: "商品签收后 7 天内无理由退货。"
    assert:
      - type: contains
        value: "7 天"
      - type: llm-rubric
        value: "语气必须亲切礼貌，且明确告知退换时效"
```

运行：
```bash
npx promptfoo eval
```

---

## 踩坑

### 1. 裁判模型自身的幻觉与自好性偏差（Self-Preference Bias）
- **现象**：当用 GPT-4o 评测 GPT-4o 生成的内容时，给出的分数普遍高于 Claude 或开源模型；或者对于字数更长的回答评分虚高（Verbosity Bias）。
- **原因**：大模型倾向于偏好与自己风格、长度相似的 Token 序列，且缺乏绝对基准标尺。
- **解法**：
  - **位置与角色翻转测试（Swap Position）**：在双模型 Pairwise（成对对比）评测时，将模型 A 和 B 的呈现顺序倒置运行两次取交集；
  - **Few-shot Calibration**：在 Judge Prompt 中强行提供带有标准评分理由的锚点样本（Anchoring Examples）；
  - **结构化打分准则（Rubric-based）**：拒绝给整体主观分，拆解成原子维度的 True/False 布尔检查列表。

### 2. 测试集污染与过拟合（Data Contamination）
- **现象**：Prompt 或系统迭代后，评测集得分从 0.7 飙升到 0.99，但上线后真实用户投诉依然严重。
- **原因**：黄金测试集的问题被硬编码进 Prompt 的 Few-shot 示例，或者模型微调训练集中混入了测试集的 Query。
- **解法**：
  - 建立测试集版本化与准入机制；
  - 保持 30% 的留存暗测试集（Hold-out Test Set），仅在发版前灰度评估；
  - 持续从线上埋点中回流 Bad Case，脱敏后扩充进自动化回归集。

### 3. 评测耗时高与 Token 费用失控
- **现象**：跑一次 500 条用例的自动化全量评测，调用 GPT-4o 裁判花费数百美元，且耗时数十分钟。
- **原因**：全量指标均调用昂贵的商业 Frontier 模型。
- **解法**：分级金字塔评测架构：
  - **L1 快速门禁（CI 每次 PR）**：正则 / 关键词匹配 + Embedding 向量余弦相似度 + 轻量模型（如 gpt-4o-mini / 8B 开源微调评测模型）；
  - **L2 夜间定时构建**：抽样 20% 核心场景运行 Ragas + Frontier 模型深度裁判。

---

## 面试怎么答

### 30 秒版本
> "测试评估大模型与 RAG 应用，核心是从传统的确定性字面匹配转变为**指标化语义评测与分层归因**：
> 1. **切片评测体系**：将 RAG 拆解为检索域与生成域。检索域重点监控上下文召回率（Context Recall）与重排精确率（Context Precision）；生成域重点监控事实忠实度（Faithfulness）与意图相关度（Answer Relevance）。
> 2. **自动化工具链**：利用 Ragas、Promptfoo 构建评测流水线，使用 LLM-as-a-Judge 配合严格的 Rubric 和 Few-shot 消除模型裁判的主观偏差。
> 3. **工程门禁闭环**：设置冷启动基线、上线前版本对比（A/B 回归）与成本/时延质量门禁（Latency, TTFT, Token Cost）。"

### 可能被追问的点

1. **什么是幻觉（Hallucination）？如何在自动化用例中检测它？**
   - *追问答法*：幻觉指模型生成了貌似合理、但违背现实或背离输入参考上下文的内容。自动化检测方法主要有：
     - **Ragas 事实命题抽取（Claim Extraction）**：先让裁判模型将 Answer 拆解成一条条原子断言（Atomic Claims），逐条检索上下文判断能否推导（Entailment），计算支持率 `Num(Supported) / Num(Total Claims)`；
     - **NLI（自然语言推理）模型验证**：使用专门训练的 NLI 分类器（如 DeBERTa-v3）判断 Context 与 Answer 的蕴涵（Entailment）或矛盾（Contradiction）关系。

2. **评测时 temperature 应该设为多少？**
   - *追问答法*：自动化功能回归和准确性评测时，被测模型与裁判模型的 `temperature` 原则上都必须设置为 **0（或极接近 0 的值）**，`top_p` 设为 1，以最大程度保证用例运行的确定性与可复现性；若需测试系统的鲁棒性或创意思维多样性，则可结合多次采样计算方差。

---

## 参考

- [Ragas 官方评估文档](https://docs.ragas.io/)
- [Promptfoo: Test and evaluate LLM apps](https://www.promptfoo.dev/)
- 相关笔记：[[05-自动化测试框架]]、[[06-接口自动化测试]]、[[Prompt 注入与大模型越权安全测试]]
