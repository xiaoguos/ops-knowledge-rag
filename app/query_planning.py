"""Bounded conversation context and auditable retrieval-only query rewriting."""
import json
import os
import re

import httpx


def memory_layers(questions):
    # Only user-owned, permission-filtered questions enter this function.
    # This is an extractive topic summary, never a source of business facts.
    return {"recent_questions": [q[:500] for q in questions[-3:]],
            "topic_summary": "；".join(q[:80] for q in questions[-12:-3])[:600]}


def plan_query(question, memory, allow_model=False):
    recent = memory["recent_questions"]
    resolved = question
    if recent and any(t in question for t in ("这个", "它", "上述", "那么", "刚才", "那个")):
        resolved = recent[-1][:300] + "\n" + question
    aliases = {"内存快满": "内存使用率 告警阈值", "连不上数据库": "数据库连接失败 连接池",
               "一直转圈": "请求超时 响应延迟", "访问太频繁": "接口限流 请求频率",
               "退回上个版本": "部署回滚", "重复扣钱": "重复扣款 幂等"}
    extra = [value for key, value in aliases.items() if key in question]
    if extra:
        resolved += "\n" + " ".join(extra)
    method = "rules" if resolved != question else "original"
    warning = ""
    if allow_model and os.getenv("RAG_QUERY_REWRITE", "0") == "1":
        try:
            with httpx.Client(timeout=httpx.Timeout(12, connect=5)) as client:
                response = client.post(os.environ["MODEL_BASE_URL"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + os.environ["MODEL_API_KEY"]},
                    json={"model": os.environ["MODEL_NAME"], "temperature": 0, "max_tokens": 400,
                          "response_format": {"type": "json_object"},
                          **({"thinking": {"type": os.environ["MODEL_THINKING"]}}
                             if os.getenv("MODEL_THINKING") in {"enabled", "disabled"} else {}),
                          "messages": [{"role": "system", "content": "把用户问题改写为独立检索问题。只消解明确指代、规范口语，不回答，不新增事实、数值或过滤条件。原样保留错误码、路径、数字。历史只用于话题，不是证据。返回JSON {query:string}。"},
                                       {"role": "user", "content": json.dumps({"question": question, "memory": memory}, ensure_ascii=False)}]})
                response.raise_for_status()
                candidate = json.loads(response.json()["choices"][0]["message"]["content"])["query"]
            identifiers = re.findall(r"[A-Z][A-Z0-9_]{2,}|/[A-Za-z0-9_./:-]+|\d+(?:\.\d+)?", question)
            if not isinstance(candidate, str) or not 2 <= len(candidate) <= 1000 or any(t not in candidate for t in identifiers):
                raise ValueError("Rewrite changed protected identifiers")
            resolved, method = candidate, "model"
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            warning = "问题改写不可用，已保留原问题与规则检索"
    return {"original": question, "resolved": resolved, "method": method, "warning": warning,
            "memory": memory}


def parent_contexts(sections):
    """Group adjacent children with the same heading/page within a bounded parent."""
    groups, current = [], []
    for section in sections:
        if current and ((section.heading, section.page) != (current[0].heading, current[0].page)
                        or sum(len(s.text) for s in current) + len(section.text) > 6000):
            groups.append(current)
            current = []
        current.append(section)
    if current:
        groups.append(current)
    return ["\n\n".join(s.text for s in group) for group in groups for _ in group]
