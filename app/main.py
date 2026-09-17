from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .platform import Platform, attach_common
from .production import Knowledge

load_dotenv()


def create_app(platform=None, embedder=None, generator=None):
    platform = platform or Platform()
    knowledge = Knowledge(platform, embedder, generator)
    app = FastAPI(title="企业内部知识库智能问答平台", version="1.0.0")
    app.state.platform = platform
    app.state.knowledge = knowledge
    app.state.handle_job = knowledge.index_job
    attach_common(app, platform)
    app.include_router(knowledge.router())
    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).resolve().parents[1] / "web", html=True),
        name="web",
    )
    return app


# Run: uvicorn app.main:create_app --factory
