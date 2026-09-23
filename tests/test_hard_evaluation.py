import json
from pathlib import Path
import pytest
from scripts.evaluate_production import validate_dataset


def test_hard_dataset_has_consistent_labels_and_version_replacements():
    root = Path(__file__).resolve().parents[1] / "data"
    corpus = json.loads((root / "hard-corpus.json").read_text(encoding="utf-8"))
    dataset = json.loads((root / "hard-evaluation.json").read_text(encoding="utf-8"))
    validate_dataset(dataset, corpus)
    assert len(dataset["cases"]) == 24
    assert sum(d.get("document_key") == "payment" for d in corpus) == 2
    assert any(d.get("tenant") == "another-tenant" for d in corpus)


def test_invalid_evidence_labels_fail_before_model_calls():
    with pytest.raises(ValueError, match="Invalid evidence"):
        validate_dataset({"cases": [{"id": "bad", "relevant": ["missing"]}]}, [{"id": "exists"}])
    with pytest.raises(ValueError, match="Refusal"):
        validate_dataset({"cases": [{"id": "bad", "relevant": ["exists"], "expected_refusal": True}]}, [{"id": "exists"}])
