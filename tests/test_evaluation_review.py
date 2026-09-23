from copy import deepcopy
import pytest
from scripts.review_evaluation import apply_reviews, review_template


def fixture():
    return {"dataset_sha256": "dataset", "details": [
        {"case_id": "r1", "strategy": "hybrid_expanded", "human_review": {}},
        {"case_id": "r2", "strategy": "hybrid_expanded", "human_review": {}}]}


def test_ungraded_items_are_not_successes_and_denominator_is_explicit():
    report = fixture()
    labels = review_template(report, "run")
    assert apply_reviews(deepcopy(report), labels, "run")["human_semantic_pass_rate"] is None
    labels["labels"][0].update(supported=True, correct=True, complete=False, reviewer="test reviewer",
                               reviewed_at="2026-09-23T10:00:00+08:00", notes="test: missing constraint")
    result = apply_reviews(report, labels, "run")
    assert result["human_semantic_pass_rate"] == 0
    assert result["human_review_summary"] == {"eligible": 2, "reviewed": 1,
                                              "unreviewed": 1, "passed_all_dimensions": 0}


def test_review_is_bound_to_run_and_requires_provenance():
    report = fixture()
    labels = review_template(report, "run")
    with pytest.raises(ValueError, match="不匹配"):
        apply_reviews(report, labels, "another")
    labels["labels"][0].update(supported=True, correct=True, complete=True)
    with pytest.raises(ValueError, match="评审人"):
        apply_reviews(report, labels, "run")
