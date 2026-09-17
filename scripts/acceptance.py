"""Opt-in real-model acceptance; imports a document and consumes model quota."""
import argparse
import getpass
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True)
    parser.add_argument("--document", required=True, type=Path)
    parser.add_argument("--department", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--followup")
    parser.add_argument("--output", type=Path, default=Path("data/runtime/live-acceptance.json"))
    parser.add_argument("--allow-write", action="store_true")
    args = parser.parse_args()
    if not args.allow_write:
        parser.error("Explicitly pass --allow-write to import data and call the real model")
    base = args.api.rstrip("/")
    if not base.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        parser.error("Remote API must use HTTPS")
    email = os.getenv("ACCEPTANCE_ADMIN_EMAIL") or input("Admin email: ")
    password = os.getenv("ACCEPTANCE_ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    version = "acceptance-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with httpx.Client(base_url=base + "/api", timeout=120) as client:
        def call(method, path, **kwargs):
            r = client.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()

        session = call("POST", "/auth/login", json={"email": email, "password": password})
        client.headers["Authorization"] = "Bearer " + session["access_token"]
        try:
            uploaded = call("POST", "/documents", data={"department": args.department, "version": version},
                            files={"file": (args.document.name, args.document.read_bytes())})
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                row = next((r for r in call("GET", "/documents") if r["id"] == uploaded["document_id"]), None)
                if row and row["status"] == "ready":
                    break
                if row and row["status"] == "failed":
                    raise RuntimeError("Document indexing failed")
                time.sleep(1)
            else:
                raise TimeoutError("Document indexing acceptance timed out")
            results = []
            for question in [args.question] + ([args.followup] if args.followup else []):
                payload = {"query": question, "department": args.department, "version": version}
                if results:
                    payload["conversation_id"] = results[0]["conversation_id"]
                answer = call("POST", "/ask", json=payload)
                evidence = {e["id"]: e["text"] for e in answer["evidence"]}
                if answer["refused"] or not answer["claims"] or not all(
                    c["citation_id"] in evidence and c["quote"] in evidence[c["citation_id"]] for c in answer["claims"]
                ):
                    raise RuntimeError("Live answer lacks valid quoted evidence")
                results.append(answer)
            history = call("GET", "/conversations/" + results[0]["conversation_id"])
            if len(history) != len(results):
                raise RuntimeError("Conversation history is incomplete")
            report = {"checked_at": datetime.now(timezone.utc).isoformat(), "model_mode": "live",
                      "document_id": uploaded["document_id"], "conversation_id": results[0]["conversation_id"],
                      "answer_count": len(results), "exact_quote_validation": True, "history_saved": True}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print("PASS: real indexing, model answers, exact citations and persisted history.")
        finally:
            call("POST", "/auth/logout")


if __name__ == "__main__":
    main()
