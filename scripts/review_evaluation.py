"""Export/import human judgements bound to an exact live evaluation report.

python -m scripts.review_evaluation --report docs/live-evaluation.json --template work/reviews.json
python -m scripts.review_evaluation --report docs/live-evaluation.json --labels work/reviews.json --output docs/reviewed-evaluation.json
"""
import argparse
import hashlib
import json
from pathlib import Path


def review_template(report, digest):
    return {"report_sha256": digest, "dataset_sha256": report["dataset_sha256"],
            "rubric": {"supported": "每条结论都被所引证据支持；引句存在不等于语义支持。",
                       "correct": "回答的事实、数值、版本正确；拒答是否符合授权范围内的资料。",
                       "complete": "覆盖问题全部必要要点；没有遗漏关键限制。"},
            "labels": [{"case_id": row["case_id"], "strategy": row["strategy"],
                        "query": row.get("query", "See source dataset"),
                        "model_output": {"refused": row.get("refused"), "claims": row.get("claims", [])},
                        "evidence": row.get("evidence", []),
                        "reviewer": "", "reviewed_at": "", "supported": None,
                        "correct": None, "complete": None, "notes": ""}
                       for row in report["details"] if "human_review" in row]}


def apply_reviews(report, labels, digest):
    if labels.get("report_sha256") != digest or labels.get("dataset_sha256") != report["dataset_sha256"]:
        raise ValueError("标注与评测结果不匹配，禁止跨运行复用标签")
    rows = {(r["case_id"], r["strategy"]): r for r in report["details"] if "human_review" in r}
    seen, passed, reviewed = set(), 0, 0
    for label in labels["labels"]:
        key = (label["case_id"], label["strategy"])
        if key not in rows or key in seen:
            raise ValueError("标注用例不存在或重复")
        seen.add(key)
        scores = [label.get(k) for k in ("supported", "correct", "complete")]
        if all(s is None for s in scores):
            continue
        if any(type(s) is not bool for s in scores):
            raise ValueError("三个维度须全部完成且为布尔值；未评测请保留null")
        if not all(isinstance(label.get(k), str) and label[k].strip()
                   for k in ("reviewer", "reviewed_at", "notes")):
            raise ValueError("已评审标签必须记录评审人、时间及依据")
        from datetime import datetime
        if datetime.fromisoformat(label["reviewed_at"]).tzinfo is None:
            raise ValueError("评审时间须包含时区")
        rows[key]["human_review"] = {k: label[k] for k in
                                   ("supported", "correct", "complete", "reviewer", "reviewed_at", "notes")}
        reviewed += 1
        passed += all(scores)
    return {**report, "human_semantic_pass_rate": passed / reviewed if reviewed else None,
            "human_review_summary": {"eligible": len(rows), "reviewed": reviewed,
                                     "unreviewed": len(rows) - reviewed, "passed_all_dimensions": passed},
            "human_review_source_report_sha256": digest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--template")
    group.add_argument("--labels")
    parser.add_argument("--output")
    args = parser.parse_args()
    raw = Path(args.report).read_bytes()
    report, digest = json.loads(raw), hashlib.sha256(raw).hexdigest()
    if args.template:
        destination, result = args.template, review_template(report, digest)
    else:
        if not args.output:
            parser.error("--labels requires --output")
        destination = args.output
        result = apply_reviews(report, json.loads(Path(args.labels).read_text(encoding="utf-8")), digest)
    # Do not overwrite an existing reviewed result or the source report.
    with Path(destination).open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    print("Review file written; ungraded items are not counted as passes.")


if __name__ == "__main__":
    main()
