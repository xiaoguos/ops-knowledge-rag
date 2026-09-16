from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Document
from test_production_platform import environment, headers, add_user

class TestEmbedder:
    __test__=False
    fingerprint="test-only:512"
    def embed(self,texts,query=False):return [[1.0]+[0.0]*511 for _ in texts]

def generator(question,evidence,history):
    return {"refused":False,"claims":[{"text":"阈值为33","citation_id":evidence[0]["id"],"quote":"33"}]}

def upload(client,admin,text="# 配置\n阈值 33",document_id=None):
    data={"department":"ops","version":"v1"}
    if document_id:data["document_id"]=document_id
    response=client.post("/api/documents",headers=admin,data=data,files={"file":("config.md",text.encode())})
    assert response.status_code==202,response.text
    return response.json()

def test_index_access_filter_and_history_ownership(environment):
    app=create_app(environment,TestEmbedder(),generator)
    with TestClient(app) as client:
        admin=headers(client)
        add_user(client,admin,"ops@example.test","member",["ops"])
        add_user(client,admin,"sales@example.test","member",["sales"])
        ops=headers(client,"ops@example.test");sales=headers(client,"sales@example.test");other=headers(client,"other@example.test")
        item=upload(client,admin)
        assert client.get("/api/documents",headers=admin).json()[0]["searchable"] is False
        app.state.handle_job(environment.claim())
        answer=client.post("/api/ask",headers=ops,json={"query":"阈值是多少"})
        assert answer.status_code==200,answer.text
        assert answer.json()["claims"] and answer.json()["evidence"]
        assert client.get("/api/documents",headers=sales).json()==[]
        assert client.post("/api/ask",headers=sales,json={"query":"阈值是多少"}).json()["refused"]
        assert client.post("/api/ask",headers=sales,json={"query":"阈值是多少","department":"ops"}).status_code==403
        assert client.get("/api/conversations/"+answer.json()["conversation_id"],headers=sales).status_code==404
        assert client.delete("/api/documents/"+item["document_id"],headers=other).status_code==404
        assert client.post("/api/documents",headers=ops,data={"department":"ops","version":"v1"},files={"file":("a.md",b"x")}).status_code==403

def test_stale_index_cannot_activate_and_delete_blocks_reindex(environment):
    app=create_app(environment,TestEmbedder(),generator)
    with TestClient(app) as client:
        admin=headers(client)
        original=upload(client,admin);first=environment.claim()
        updated=upload(client,admin,"# 配置\n阈值 99",original["document_id"]);second=environment.claim()
        app.state.handle_job(second)
        with environment.Session() as db:active=db.get(Document,original["document_id"]).active_version
        app.state.handle_job(first)
        with environment.Session() as db:assert db.get(Document,original["document_id"]).active_version==active
        upload(client,admin,"# 配置\n阈值 77",original["document_id"]);pending=environment.claim()
        assert client.delete("/api/documents/"+original["document_id"],headers=admin).status_code==200
        app.state.handle_job(pending)
        assert client.get("/api/documents",headers=admin).json()==[]
        assert client.post("/api/ask",headers=admin,json={"query":"阈值是多少"}).json()["refused"]

def test_failed_update_preserves_active_version(environment):
    embedder=TestEmbedder();app=create_app(environment,embedder,generator)
    with TestClient(app) as client:
        admin=headers(client);item=upload(client,admin)
        app.state.handle_job(environment.claim())
        upload(client,admin,"# 更新\n阈值 99",item["document_id"])
        job=environment.claim()
        environment.fail(job,"embedding unavailable")
        listed=client.get("/api/documents",headers=admin).json()[0]
        assert listed["status"]=="failed" and listed["searchable"]
        assert client.post("/api/documents/"+item["document_id"]+"/retry",headers=admin).status_code==202
        assert client.post("/api/documents/"+item["document_id"]+"/retry",headers=admin).status_code==409
        app.state.handle_job(environment.claim())
        assert client.get("/api/documents",headers=admin).json()[0]["status"]=="ready"
