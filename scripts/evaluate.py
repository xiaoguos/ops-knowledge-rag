"""Repeatable fixed-split retrieval baseline; no fabricated LLM accuracy."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import tempfile
from app.service import RagService


def main():
    root = Path(__file__).resolve().parents[1]
    dataset = json.loads((root / "data/evaluation.json").read_text(encoding="utf-8"))
    dataset = [q for q in dataset if q["split"] == "test"]
    results = []
    with tempfile.TemporaryDirectory() as directory:
        service = RagService(directory)
        service.seed()
        for strategy in ["bm25", "vector", "hybrid", "adaptive"]:
            recalls, answers, false_refusals, correct_refusals, latencies = [], [], [], [], []
            details = []
            for q in dataset:
                response = service.ask(q["query"], strategy=strategy, department=q["department"], version=q["version"])
                ids = {h["document_id"] for h in response["hits"]}
                if q["answerable"]:
                    recall = len(ids & set(q["relevant_document_ids"])) / len(q["relevant_document_ids"])
                    recalls.append(recall)
                    answers.append(not response["refused"] and q["answer_contains"] in response["answer"])
                    false_refusals.append(response["refused"])
                else:
                    correct_refusals.append(response["refused"])
                latencies.append(response["latency_ms"])
                details.append({"question_id": q["id"], "refused": response["refused"], "retrieved_document_ids": sorted(ids), "answer_keyword_hit": bool(q["answer_contains"] and q["answer_contains"] in response["answer"])})
            avg = lambda xs: round(statistics.mean(xs), 4) if xs else None
            results.append({"strategy": strategy, "recall_at_5": avg(recalls), "answer_keyword_accuracy": avg(answers), "false_refusal_rate": avg(false_refusals), "correct_refusal_rate": avg(correct_refusals), "mean_latency_ms": avg(latencies), "details": details})
        report = {"generated_at": datetime.now(timezone.utc).isoformat(), "scope": "自建小样本，4 条开发题与 28 条固定测试题；文档级 Recall@5。关键词检查不等于人工准确率，不评估真实 LLM 幻觉率。", "test_count": len(dataset), "answerable_count": sum(q["answerable"] for q in dataset), "embedding": service.embedder.fingerprint, "generation": os.getenv("RAG_GENERATION", "extractive"), "results": results}
    output_name = "evaluation-semantic.json" if os.getenv("RAG_EMBEDDING", "hash") != "hash" else "evaluation.json"
    for path in [root / "docs" / output_name, root / "web" / output_name]:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"embedding": report["embedding"], "results": [{k:v for k,v in row.items() if k != "details"} for row in results]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
