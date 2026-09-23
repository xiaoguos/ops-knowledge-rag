from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from app.ingestion import layout_text, process_document, reviewed_report
from app.main import create_app
from app.models import DocumentVersion
from test_production_knowledge import TestEmbedder, generator, upload
from test_production_platform import headers, add_user


def pdf(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=300, height=300)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def region(text="阈值33", confidence=.96):
    return {"text": text, "confidence": confidence, "box": [[0, 0], [100, 0], [100, 20], [0, 20]]}


def positioned(text, x, y):
    return {"text": text, "confidence": .99,
            "box": [[x, y], [x + 100, y], [x + 100, y + 20], [x, y + 20]]}


def test_simple_table_is_a_reviewable_candidate_not_flat_lines():
    cells = [positioned(value, x, y) for y, values in [(0, ["参数", "值"]),
             (40, ["超时", "3000毫秒"]), (80, ["连接池", "30"])]
             for x, value in zip([0, 250], values)]
    text, layout = layout_text(list(reversed(cells)))
    assert "| 参数 | 值 |\n| --- | --- |" in text
    assert "| 超时 | 3000毫秒 |" in text
    assert layout == {"table_candidates": 1, "ambiguous_columns": False}


def test_unaligned_columns_are_not_filled_with_invented_cells():
    cells = [positioned("左段", 0, 0), positioned("右段", 250, 0),
             positioned("合并单元格或正文", 0, 40)]
    text, layout = layout_text(cells)
    assert "---" not in text
    assert layout == {"table_candidates": 0, "ambiguous_columns": True}
    assert "合并单元格或正文" in text


def test_scanned_pages_are_not_silently_dropped(monkeypatch):
    monkeypatch.setattr("app.ingestion.render_page", lambda payload, n: bytes([n]))
    report = process_document("scan.pdf", pdf(2), ocr=lambda png: [region()] if png == b"\x01" else [])
    assert report["review_required"]
    assert len(report["pages"]) == 2
    assert report["sections"][0]["page"] == 1
    with pytest.raises(ValueError, match="空页"):
        reviewed_report(report, [{"page": 1, "text": "阈值33", "blank": False},
                                 {"page": 2, "text": "", "blank": False}])
    accepted = reviewed_report(report, [{"page": 1, "text": "阈值45", "blank": False},
                                       {"page": 2, "text": "", "blank": True}])
    assert accepted["reviewed"] and not accepted["review_required"]
    assert accepted["sections"][0]["text"] == "阈值45"


def test_low_ocr_score_routes_to_vision_but_still_requires_review(monkeypatch):
    monkeypatch.setattr("app.ingestion.render_page", lambda *args: b"image")
    calls = []
    def vision(png):
        calls.append(png)
        return "| 参数 | 数值 |\n| --- | --- |\n| 阈值 | 45 |"
    report = process_document("scan.pdf", pdf(), ocr=lambda png: [region(confidence=.4)], vision=vision)
    assert calls == [b"image"]
    assert report["pages"][0]["method"] == "vision"
    assert report["review_required"]
    assert "45" in report["sections"][0]["text"]


def test_text_document_does_not_invoke_ocr():
    def denied(*args):
        raise AssertionError("Native text should not need OCR")
    report = process_document("manual.md", b"# Title\nValue 33", ocr=denied, vision=denied)
    assert not report["review_required"]
    assert report["sections"][0]["heading"] == "Title"


def test_page_limit_applies_before_ocr(monkeypatch):
    monkeypatch.setattr("app.ingestion.render_page", lambda *args: pytest.fail("Must reject first"))
    with pytest.raises(ValueError, match="60"):
        process_document("large.pdf", pdf(61))


def test_review_gate_stale_review_and_index_recovery(environment, monkeypatch):
    app = create_app(environment, TestEmbedder(), generator)
    with TestClient(app) as client:
        admin = headers(client)
        add_user(client, admin, "member@example.test", "member", ["ops"])
        member = headers(client, "member@example.test")
        other = headers(client, "other@example.test")
        original = upload(client, admin)
        app.state.handle_job(environment.claim())
        old = client.get("/api/documents", headers=admin).json()[0]
        report = {"schema": 1, "review_required": True, "sections": [],
                  "pages": [{"page": 1, "text": "阈值99", "method": "ocr", "regions": [], "warnings": ["复核"]}]}
        monkeypatch.setattr("app.production.process_document", lambda *args: report)
        response = client.post("/api/documents", headers=admin,
            data={"department": "ops", "version": "v2", "document_id": original["document_id"]},
            files={"file": ("scan.pdf", pdf())})
        assert response.status_code == 202
        app.state.handle_job(environment.claim())
        listed = client.get("/api/documents", headers=admin).json()[0]
        assert listed["status"] == "awaiting_review" and listed["searchable"] == old["searchable"]
        path = "/api/documents/" + original["document_id"]
        assert client.get(path + "/processing", headers=member).status_code == 403
        assert client.get(path + "/processing", headers=other).status_code == 404
        data = client.get(path + "/processing", headers=admin).json()
        body = {"version_id": data["version_id"], "digest": data["digest"],
                "pages": [{"page": 1, "text": "阈值33", "blank": False}]}
        assert client.post(path + "/review", headers=admin, json={**body, "digest": "0" * 64}).status_code == 409
        assert client.post(path + "/review", headers=member, json=body).status_code == 403
        assert client.post(path + "/review", headers=admin, json=body).status_code == 202
        assert client.post(path + "/review", headers=admin, json=body).status_code == 409
        monkeypatch.setattr("app.production.process_document", lambda *args: pytest.fail("Approved text must not be re-OCRed"))
        app.state.handle_job(environment.claim())
        assert client.get("/api/documents", headers=admin).json()[0]["status"] == "ready"
        answer = client.post("/api/ask", headers=member, json={"query": "阈值是多少"}).json()
        assert answer["evidence"][0]["page"] == 1
        assert answer["evidence"][0]["version_id"] == data["version_id"]
        assert answer["evidence"][0]["text"] == "阈值33"
        with environment.Session() as db:
            assert db.get(DocumentVersion, data["version_id"]).processing["reviewed"]
        monkeypatch.setattr("app.production.render_page", lambda *args: b"png-fixture")
        page_path = path + "/versions/" + data["version_id"] + "/pages/1"
        assert client.get(page_path, headers=member).content == b"png-fixture"
        assert client.get(page_path, headers=other).status_code == 404
        client.delete(path, headers=admin)
        assert client.get(page_path, headers=member).status_code == 404
