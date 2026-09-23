from fastapi.testclient import TestClient
import json
import pytest
from app.main import create_app
from app.models import Document
from test_production_platform import headers, add_user


@pytest.mark.parametrize(
    "citation,quote,refused,expected",
    [
        ("e1", "阈值33", False, False),
        ("invented", "阈值33", False, True),
        ("e1", "阈值99", False, True),
        ("e1", "阈值33", True, True),
    ],
)
def test_production_model_citation_contract(
    environment, monkeypatch, citation, quote, refused, expected
):
    from app.production import Knowledge

    payload = {
        "claims": [{"text": "阈值为33", "citation_id": citation, "quote": quote}],
        "refused": refused,
    }

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setenv("MODEL_BASE_URL", "https://model.example.test/v1")
    monkeypatch.setenv("MODEL_NAME", "test-model")
    monkeypatch.setattr("app.production.httpx.Client", Client)
    result = Knowledge(environment, TestEmbedder()).generate(
        "阈值是多少", [{"id": "e1", "text": "阈值33"}], []
    )
    assert result["refused"] is expected


class TestEmbedder:
    __test__ = False
    fingerprint = "test-only:512"

    def embed(self, texts, query=False):
        return [[1.0] + [0.0] * 511 for _ in texts]


def generator(question, evidence, history):
    return {
        "refused": False,
        "claims": [
            {"text": "阈值为33", "citation_id": evidence[0]["id"], "quote": "33"}
        ],
    }


def upload(client, admin, text="# 配置\n阈值 33", document_id=None):
    data = {"department": "ops", "version": "v1"}
    if document_id:
        data["document_id"] = document_id
    response = client.post(
        "/api/documents",
        headers=admin,
        data=data,
        files={"file": ("config.md", text.encode())},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_index_access_filter_and_history_ownership(environment):
    app = create_app(environment, TestEmbedder(), generator)
    with TestClient(app) as client:
        admin = headers(client)
        add_user(client, admin, "ops@example.test", "member", ["ops"])
        add_user(client, admin, "sales@example.test", "member", ["sales"])
        ops = headers(client, "ops@example.test")
        sales = headers(client, "sales@example.test")
        other = headers(client, "other@example.test")
        item = upload(client, admin)
        assert (
            client.get("/api/documents", headers=admin).json()[0]["searchable"] is False
        )
        app.state.handle_job(environment.claim())
        answer = client.post("/api/ask", headers=ops, json={"query": "阈值是多少"})
        assert answer.status_code == 200, answer.text
        assert answer.json()["claims"] and answer.json()["evidence"]
        assert client.get("/api/documents", headers=sales).json() == []
        assert client.post(
            "/api/ask", headers=sales, json={"query": "阈值是多少"}
        ).json()["refused"]
        assert (
            client.post(
                "/api/ask",
                headers=sales,
                json={"query": "阈值是多少", "department": "ops"},
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/conversations/" + answer.json()["conversation_id"], headers=sales
            ).status_code
            == 404
        )
        assert (
            client.delete(
                "/api/documents/" + item["document_id"], headers=other
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/documents",
                headers=ops,
                data={"department": "ops", "version": "v1"},
                files={"file": ("a.md", b"x")},
            ).status_code
            == 403
        )


def test_stale_index_cannot_activate_and_delete_blocks_reindex(environment):
    app = create_app(environment, TestEmbedder(), generator)
    with TestClient(app) as client:
        admin = headers(client)
        original = upload(client, admin)
        first = environment.claim()
        upload(client, admin, "# 配置\n阈值 99", original["document_id"])
        second = environment.claim()
        app.state.handle_job(second)
        with environment.Session() as db:
            active = db.get(Document, original["document_id"]).active_version
        app.state.handle_job(first)
        with environment.Session() as db:
            assert db.get(Document, original["document_id"]).active_version == active
        upload(client, admin, "# 配置\n阈值 77", original["document_id"])
        pending = environment.claim()
        assert (
            client.delete(
                "/api/documents/" + original["document_id"], headers=admin
            ).status_code
            == 200
        )
        app.state.handle_job(pending)
        assert client.get("/api/documents", headers=admin).json() == []
        assert client.post(
            "/api/ask", headers=admin, json={"query": "阈值是多少"}
        ).json()["refused"]


def test_revoked_department_history_is_not_used_for_query_memory(environment):
    app = create_app(environment, TestEmbedder(), generator)
    with TestClient(app) as client:
        admin = headers(client)
        member = add_user(client, admin, "memory@example.test", "member", ["ops"])
        login = headers(client, "memory@example.test")
        upload(client, admin)
        app.state.handle_job(environment.claim())
        first = client.post("/api/ask", headers=login, json={"query": "ops阈值是多少"}).json()
        response = client.put("/api/users/" + member["id"], headers=admin,
                              json={"active": True, "role": "member", "departments": ["sales"]})
        assert response.status_code == 200
        login = headers(client, "memory@example.test")
        follow = client.post("/api/ask", headers=login,
                            json={"query": "那么它呢", "conversation_id": first["conversation_id"]}).json()
        assert follow["retrieval_plan"]["memory"]["recent_questions"] == []
        assert follow["refused"] and follow["evidence"] == []


def test_failed_update_preserves_active_version(environment):
    embedder = TestEmbedder()
    app = create_app(environment, embedder, generator)
    with TestClient(app) as client:
        admin = headers(client)
        item = upload(client, admin)
        app.state.handle_job(environment.claim())
        upload(client, admin, "# 更新\n阈值 99", item["document_id"])
        job = environment.claim()
        environment.fail(job, "embedding unavailable")
        listed = client.get("/api/documents", headers=admin).json()[0]
        assert listed["status"] == "failed" and listed["searchable"]
        assert (
            client.post(
                "/api/documents/" + item["document_id"] + "/retry", headers=admin
            ).status_code
            == 202
        )
        assert (
            client.post(
                "/api/documents/" + item["document_id"] + "/retry", headers=admin
            ).status_code
            == 409
        )
        app.state.handle_job(environment.claim())
        assert (
            client.get("/api/documents", headers=admin).json()[0]["status"] == "ready"
        )
