from app.documents import split_markdown
from app.query_planning import memory_layers, parent_contexts, plan_query
from scripts.evaluate_production import retrieval_metrics
import httpx
import json
import pytest


def test_recent_and_older_topics_have_separate_budgets():
    memory = memory_layers([str(i) * 1000 for i in range(20)])
    assert len(memory["recent_questions"]) == 3
    assert all(len(q) <= 500 for q in memory["recent_questions"])
    assert len(memory["topic_summary"]) <= 600


def test_identifier_preserved_in_oral_and_followup_query():
    plan = plan_query("它一直转圈，PAY_TIMEOUT怎么办？", memory_layers(["支付接口的处理流程"] ))
    assert "PAY_TIMEOUT" in plan["resolved"]
    assert "支付接口" in plan["resolved"] and "响应延迟" in plan["resolved"]
    assert plan["original"] == "它一直转圈，PAY_TIMEOUT怎么办？"


def test_parent_expansion_keeps_table_atomic_and_groups_children():
    sections = split_markdown("# 手册\n" + "说明" * 800 + "\n## 表格\n| 参数 | 数值 |\n| 阈值 | 45 |")
    assert max(len(s.text) for s in sections) <= 700
    parents = parent_contexts(sections)
    assert len(parents[0]) > len(sections[0].text)
    assert "阈值" not in parents[0]
    assert "| 阈值 | 45 |" in sections[-1].text


def test_recall_counts_unique_gold_documents_not_keyword_hits():
    assert retrieval_metrics(["a", "a", "x"], ["a", "b"])["recall_at_5"] == .5
    assert retrieval_metrics(["a"], ["a", "b"])["all_evidence_at_5"] is False
    assert retrieval_metrics(["a"], [])["recall_at_5"] is None


@pytest.mark.parametrize("candidate", ["查询支付故障", "PAY_TIMEOUT等待30秒", "x" * 1001, None])
def test_model_rewrite_cannot_drop_identifiers_or_overrun_budget(monkeypatch, candidate):
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, *args, **kwargs):
            return httpx.Response(200, request=httpx.Request("POST", "https://test.invalid"),
                                  json={"choices": [{"message": {"content": json.dumps({"query": candidate})}}]})
    monkeypatch.setattr("app.query_planning.httpx.Client", Client)
    monkeypatch.setenv("MODEL_BASE_URL", "https://test.invalid")
    monkeypatch.setenv("MODEL_NAME", "test")
    monkeypatch.setenv("MODEL_API_KEY", "test-only")
    monkeypatch.setenv("RAG_QUERY_REWRITE", "1")
    question = "PAY_TIMEOUT在/api/orders超时3000毫秒怎么办？"
    result = plan_query(question, memory_layers([]), True)
    assert result["resolved"] == question
    assert result["method"] == "original" and result["warning"]
