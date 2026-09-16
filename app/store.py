import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from .documents import parse_file


class Store:
    def __init__(self, path, embedder):
        self.path, self.embedder = str(path), embedder
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, department TEXT NOT NULL,
                    version TEXT NOT NULL, digest TEXT NOT NULL, embedding_model TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks(
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    heading TEXT, text TEXT, page INTEGER, vector TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def upsert(self, document_id, name, payload, department="运维", version="1.0"):
        digest = hashlib.sha256(payload).hexdigest()
        with self.connect() as db:
            old = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
            if old and (old["digest"], old["department"], old["version"], old["title"], old["embedding_model"]) == (digest, department, version, name, self.embedder.fingerprint):
                return {"id": document_id, "changed": False}
        sections = parse_file(name, payload)
        if not sections:
            raise ValueError("文档内容为空")
        # Expensive or fallible work precedes the transaction. Old content survives errors.
        vectors = self.embedder.embed([s.heading + "\n" + s.text for s in sections])
        if len(vectors) != len(sections):
            raise ValueError("切片与向量数量不一致")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (document_id, name, department, version, digest, self.embedder.fingerprint, datetime.now(timezone.utc).isoformat()))
            for i, (section, vector) in enumerate(zip(sections, vectors)):
                chunk_id = hashlib.sha256(f"{document_id}:{digest}:{i}".encode()).hexdigest()[:20]
                db.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", (chunk_id, document_id, section.heading, section.text, section.page, json.dumps(vector)))
        return {"id": document_id, "changed": True, "chunks": len(sections)}

    def delete(self, document_id):
        with self.connect() as db:
            return db.execute("DELETE FROM documents WHERE id=?", (document_id,)).rowcount > 0

    def documents(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.document_id=d.id) AS chunks FROM documents d ORDER BY d.id")]

    def chunks(self, department=None, version=None):
        clauses, params = [], []
        for column, value in [("department", department), ("version", version)]:
            if value:
                clauses.append(f"d.{column}=?"); params.append(value)
        query = "SELECT c.*, d.title, d.department, d.version, d.embedding_model FROM chunks c JOIN documents d ON d.id=c.document_id"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with self.connect() as db:
            return [dict(row) for row in db.execute(query + " ORDER BY c.id", params)]
