from contextlib import asynccontextmanager
import os
from pathlib import Path
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from .service import RagService

load_dotenv()


class Question(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    strategy: str = "adaptive"
    department: str | None = None
    version: str | None = None
    k: int = Field(default=5, ge=1, le=20)
    rerank: bool = False
    history: list[str] = Field(default_factory=list, max_length=6)


def create_app(directory=None):
    service = RagService(directory or os.getenv("RAG_DATA_DIR", "data/runtime"))

    @asynccontextmanager
    async def lifespan(app):
        if not service.store.documents():
            service.seed()
        yield

    app = FastAPI(title="Ops Knowledge RAG", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "https://xiaoguos.github.io").split(","), allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization"])

    def authorize(authorization: str | None = Header(default=None)):
        import secrets
        token = os.getenv("API_TOKEN", "")
        if token and not secrets.compare_digest(authorization or "", "Bearer " + token):
            raise HTTPException(401, "访问令牌不正确")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "embedding": service.embedder.fingerprint, "generation": os.getenv("RAG_GENERATION", "extractive"), "authorization": bool(os.getenv("API_TOKEN"))}

    @app.get("/api/documents", dependencies=[Depends(authorize)])
    def documents():
        return service.store.documents()

    @app.post("/api/documents", dependencies=[Depends(authorize)])
    def upload(file: UploadFile = File(), document_id: str = Form(), department: str = Form("运维"), version: str = Form("1.0")):
        if not document_id or len(document_id) > 120:
            raise HTTPException(422, "document_id 必须是 1–120 个字符")
        payload = file.file.read(8 * 1024 * 1024 + 1)
        if len(payload) > 8 * 1024 * 1024:
            raise HTTPException(413, "文件上限 8MB")
        try:
            return service.store.upsert(document_id, Path(file.filename or "upload.md").name, payload, department, version)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except httpx.HTTPError as error:
            raise HTTPException(502, "向量服务不可用；旧索引保持不变") from error

    @app.delete("/api/documents/{document_id}", dependencies=[Depends(authorize)])
    def delete(document_id: str):
        if not service.store.delete(document_id):
            raise HTTPException(404, "文档不存在")
        return {"deleted": document_id}

    @app.post("/api/ask", dependencies=[Depends(authorize)])
    def ask(question: Question):
        try:
            return service.ask(**question.model_dump())
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except httpx.HTTPError as error:
            raise HTTPException(502, "模型服务不可用，请检查服务配置或稍后重试") from error

    app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True), name="web")
    return app


app = create_app()
