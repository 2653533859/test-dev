---
created: 2026-09-30
tags: [AI与大模型测试/RAG评测]
---

# RAG 检索增强生成系统质量评测（RAGAS 实战）

> 针对基于企业知识库与向量数据库的 RAG（Retrieval-Augmented Generation）架构，实现检索质量与生成质量分层隔离量化的自动化评测方案。

## 概念

企业内部的智能客服、技术文档问答、代码辅助助手大多基于 **RAG（检索增强生成）** 架构。系统先从向量数据库（Milvus / Pinecone / Chroma）中召回与问题相似的文档分块（Chunks），然后将其作为上下文（Context）输入大模型生成最终回答。

在实际测试中，经常出现“回答错误”的情况。**测试开发工程师的核心价值，在于精准区分问题究竟出在「检索召回层」还是「模型生成层」**：

```text
                                用户提问 (Query)
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │     1. 检索检索层      │             │     2. 生成总结层      │
        │ (Embedding + 向量检索) │             │ (Prompt 注入 + 大模型) │
        └───────────┬───────────┘             └───────────┬───────────┘
                    │                                     │
                    ▼                                     ▼
         [ 检索质量核心指标 ]                     [ 生成质量核心指标 ]
    • Context Precision (精确率)            • Faithfulness (忠实度/反幻觉)
      (召回的切片是否排在前面)                (回答是否全部来源于上下文)
    • Context Recall (召回率)               • Answer Relevance (答案相关性)
      (是否涵盖所有答题必备事实)              (回答是否切中用户提问主题)
```

### RAGAS 评测四大金标准

1. **忠实度（Faithfulness）**：
   - 衡量生成回答中的每一句话，是否都能在检索出的 Context 中找到依据。若模型输出了 Context 中未提及的内容，即为**幻觉（Hallucination）**。
2. **答案相关度（Answer Relevance）**：
   - 衡量生成的答案是否直接回答了用户的核心疑问，惩罚废话和不完整回答。
3. **上下文精确率（Context Precision）**：
   - 衡量所有召回的 Chunks 中，真正包含答案的有效切片是否排在靠前的 Top 顺位。
4. **上下文召回率（Context Recall）**：
   - 衡量知识库检索出的上下文，是否完全覆盖了黄金参考答案（Ground Truth）所需的全部关键事实点。

---

## 用法

### 使用 Ragas 框架进行全自动化批量评测

安装核心评测依赖：`pip install ragas datasets langchain-openai`。

```python
import os
import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevance,
    context_precision,
    context_recall,
)

# 准备评测测试数据集（自动化测试用例集合）
# 每个用例包含：用户问句、真实被测 RAG 召回的文档切片、被测 RAG 生成的回答、标准答案
eval_data = {
    "question": [
        "企业内部员工请病假超过三天需要什么材料？",
        "自动化测试框架中 conftest.py 的作用域有哪些？"
    ],
    "contexts": [
        [
            "根据《员工考勤管理制度》第4条，员工请病假1-2天需部门经理审批并提交就医记录挂号单；",
            "请病假3天及以上（含3天），必须提供二级甲等及以上医院开具的诊断证明原件及病休建议书。"
        ],
        [
            "pytest 框架中，conftest.py 用于存放共享 fixture。",
            "fixture 的 scope 支持 session、package、module、class 和 function 五种级别。"
        ]
    ],
    "answer": [
        "请病假超过3天需要二级甲等及以上医院的诊断证明原件和病休建议单。",
        "conftest.py 中的 fixture 作用域包括 session、module、class 和 function 四种。" # 故意遗漏 package 作为负向样本
    ],
    "ground_truth": [
        "必须提供二级甲等及以上医院开具的诊断证明原件及病休建议书。",
        "支持 session、package、module、class、function 共五种级别。"
    ]
}

def run_rag_eval_pipeline():
    """自动化 RAG 质量度量与门禁判断"""
    dataset = Dataset.from_dict(eval_data)
    
    # 选定 RAGAS 四大核心度量算子
    metrics = [
        faithfulness,
        answer_relevance,
        context_precision,
        context_recall,
    ]
    
    # 执行自动化打分（底层使用配置的大模型进行句子级逻辑蕴含推理）
    results = evaluate(
        dataset=dataset,
        metrics=metrics,
    )
    
    df_result = results.to_pandas()
    print("\n========== RAG 自动化评测得分表 ==========")
    print(df_result[["question", "faithfulness", "answer_relevance", "context_recall"]])
    
    # CI/CD 质量门禁阻断逻辑
    avg_faithfulness = df_result["faithfulness"].mean()
    avg_recall = df_result["context_recall"].mean()
    
    print(f"\n平均忠实度 (Faithfulness): {avg_faithfulness:.2f}")
    print(f"平均召回率 (Context Recall): {avg_recall:.2f}")
    
    # 门禁断言：在知识库问答系统中，忠实度（防胡说）必须达到 0.90 以上
    assert avg_faithfulness >= 0.90, f"RAG 生成出现严重幻觉，忠实度不达标: {avg_faithfulness}"
    assert avg_recall >= 0.85, f"检索召回漏掉关键事实，召回率不达标: {avg_recall}"

if __name__ == "__main__":
    run_rag_eval_pipeline()
```

---

## 踩坑

1. **混淆了“检索漏掉”与“模型胡说”**：
   - 业务反馈“机器人回答错误”，测试直接给算法提 bug 称模型不行；排查发现是文档解析（PDF/Word 切割）时表格丢失，导致向量库里根本没有这段文字，模型只得依据世界知识强行回答。
   - **解法**：先看 `Context Recall`，如果召回率低，说明问题出在文档解析器（Parser）、Chunk 分块大小或向量模型上；只有当 `Context Recall` 为 1.0 但 `Faithfulness` 很低时，才是大模型提示词设计（System Prompt）没有强约束“只允许基于上下文作答”。
2. **Top-K 截断与中间迷失（Lost in the Middle）**：
   - 压测为了省 Token 将 Top-K 设为 3，导致多段交叉事实回答不全；而调大到 Top-K=20 时，模型由于注意力偏向两端，容易忽略夹在中间的关键上下文。
   - **解法**：在自动化用例中设计“关键证据放置在第 1、第 5、第 10 个 Chunk”的位置扰动测试集，推动研发接入重排模型（Reranker，如 BGE-Reranker）将相关度最高的切片精排到首位。

---

## 面试怎么答

> **面试官会怎么问**：
> 你们测试团队是怎么评测企业 RAG 知识库问答效果的？怎么衡量有没有幻觉？

**30 秒回答骨架**：
> “我们采用的是 **RAGAS 框架** 分层解耦的自动化评测体系。将 RAG 拆解为**检索层**与**生成层**两个阶段独立度量：
> - **检索层**重点监控 `Context Recall`（是否搜到了标准答案所依赖的事实切片）与 `Context Precision`（高质量证据是否排在 Top 3）；
> - **生成层**重点监控 `Faithfulness`（忠实度/反幻觉率：通过 NLI 自然语言推理判断模型输出的断言能否被召回上下文完全支撑）与 `Answer Relevance`（是否切题）。
> 我们建立了包含 300+ 真实业务 Query 的黄金测试基准，在流水线微调向量模型或修改分块策略时自动回归这四项得分，忠实度低于 0.92 直接阻断发布。”

---

## 参考

- [[15-AI与大模型测试]] —— 大模型评测 MOC
- [[大语言模型（LLM）自动化评测体系与指标]] —— 裁判模型通用指标
- [[04-数据库]] —— 向量数据库与检索
