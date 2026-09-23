"""Evaluate the actual Knowledge implementation in an isolated database.

Default: real BGE retrieval only, no paid generation. --live enables generation.
Human semantic labels remain null until reviewed; never infer them from quotes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from app.models import Document, DocumentVersion
from app.platform import Base, Job, Platform, User
from app.production import Knowledge
from app.query_planning import memory_layers, plan_query


def retrieval_metrics(hits, expected):
    found = set(hits)
    gold = set(expected)
    return {"recall_at_5": len(found & gold) / len(gold) if gold else None,
            "all_evidence_at_5": gold <= found if gold else None}


def mean(values):
    present = [v for v in values if v is not None]
    return round(statistics.mean(present), 4) if present else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--cases", help="Comma-separated case IDs for a bounded live run")
    parser.add_argument("--output", default="docs/production-evaluation.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cases_path = root / "data/production-evaluation.json"
    dataset = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = dataset["cases"][:args.limit or None]
    if args.limit < 0:
        parser.error("--limit must be nonnegative")
    if args.cases:
        ids = set(args.cases.split(","))
        if not ids <= {c["id"] for c in dataset["cases"]}:
            parser.error("Unknown case IDs")
        cases = [c for c in cases if c["id"] in ids]
    if not cases:
        parser.error("No cases selected")
    corpus = json.loads((root / "data/corpus.json").read_text(encoding="utf-8"))
    os.environ["APP_ENV"] = "test"
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        platform = Platform("sqlite:///" + (Path(temp) / "evaluation.db").as_posix())
        try:
            Base.metadata.create_all(platform.engine)
            service = Knowledge(platform)
            names = {}
            for item in corpus:
                with platform.transaction() as db:
                    doc = Document(tenant="evaluation", owner_id="evaluation", revision=1)
                    db.add(doc)
                    db.flush()
                    payload = item["content"].encode()
                    version = DocumentVersion(document_id=doc.id, revision=1, filename=item["title"] + ".md",
                        department=item["department"], version=item["version"], payload=payload,
                        digest=hashlib.sha256(payload).hexdigest())
                    db.add(version)
                    db.flush()
                    db.add(Job(tenant="evaluation", owner_id="evaluation", kind="index", payload={"version_id": version.id}))
                    names[doc.id] = item["id"]
                service.index_job(platform.claim())
            for case in cases:
                user = User(id="evaluation", tenant="evaluation", role="member" if "departments" in case else "admin",
                            departments=case.get("departments", []))
                for strategy in ("bm25", "vector", "hybrid", "hybrid_expanded"):
                    plan = plan_query(case["query"], memory_layers([]))
                    expanded = strategy == "hybrid_expanded"
                    started = time.perf_counter()
                    hits = service.search(user, plan["resolved"] if expanded else case["query"],
                        version_label=case.get("version"), strategy="hybrid" if expanded else strategy,
                        k=5, original=case["query"], expand_parent=expanded)
                    ids = [names[h["document_id"]] for h in hits]
                    row = {"case_id": case["id"], "family": case["family"], "strategy": strategy,
                           **retrieval_metrics(ids, case["relevant"]),
                           "retrieved": ids, "retrieval_ms": round((time.perf_counter() - started) * 1000, 2),
                           "permission_pass": all(user.role == "admin" or h["department"] in user.departments for h in hits)}
                    if args.live and expanded:
                        started = time.perf_counter()
                        try:
                            answer = service.generate(case["query"], hits, memory_layers([])) if hits else {"refused": True, "claims": []}
                            row.update(answer)
                            row["refusal_match"] = answer["refused"] == case.get("expected_refusal", False)
                            evidence = {h["id"]: h["text"] for h in hits}
                            row["citation_contract_pass"] = (bool(answer["claims"]) and all(
                                c["citation_id"] in evidence and c["quote"] in evidence[c["citation_id"]]
                                for c in answer["claims"])) if not answer["refused"] else None
                            row["evidence"] = hits
                            row["human_review"] = {"supported": None, "correct": None, "complete": None, "notes": ""}
                        except Exception as error:
                            row["generation_error"] = type(error).__name__
                        row["generation_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    rows.append(row)
                print(case["id"] + " completed", flush=True)
        finally:
            platform.engine.dispose()
    summary = []
    for strategy in ("bm25", "vector", "hybrid", "hybrid_expanded"):
        subset = [r for r in rows if r["strategy"] == strategy]
        summary.append({"strategy": strategy, "cases": len(subset),
                        "answerable_cases": sum(r["recall_at_5"] is not None for r in subset),
                        "recall_at_5": mean(r["recall_at_5"] for r in subset),
                        "all_evidence_at_5": mean(r["all_evidence_at_5"] for r in subset),
                        "permission_cases": sum(r["family"] == "permission" for r in subset),
                        "permission_pass_rate": mean(r["permission_pass"] for r in subset if r["family"] == "permission"),
                        "generation_attempts": sum("generation_ms" in r for r in subset),
                        "generation_errors": sum("generation_error" in r for r in subset),
                        "refusal_match_rate": mean(r.get("refusal_match") for r in subset),
                        "citation_contract_pass_rate": mean(r.get("citation_contract_pass") for r in subset),
                        "mean_retrieval_ms": mean(r["retrieval_ms"] for r in subset)})
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "scope": dataset["scope"],
              "entrypoint": "app.production.Knowledge", "database": "isolated SQLite; not a PostgreSQL load test",
              "embedding": service.embedder.fingerprint, "generation": "live" if args.live else "not_run",
              "case_count": len(cases), "dataset_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
              "metric_unit": "unique gold document coverage among the first 5 evidence items; unanswerable excluded from recall",
              "summary": summary, "human_semantic_pass_rate": None, "details": rows}
    path = root / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"case_count": len(cases), "summary": summary}, ensure_ascii=False))


if __name__ == "__main__":
    main()
