"""Strict plain-text system-link check required by spec 2.7."""

import re


def evaluate(instance):
    response = instance.get("response") or {}
    text = response if isinstance(response, str) else "".join(
        part.get("text", "") for part in response.get("parts", [])
    )
    if re.search(r"\[[^\]]*\]\(\s*https?://[^)]*\)", text):
        return {"score": 0, "explanation": "使用了 Markdown 連結"}
    if str(instance.get("eval_case_id", "")).startswith("off_topic"):
        return {"score": 1, "explanation": "離題拒答案例不需連結"}
    present = bool(re.search(r"https?://[^\s<>]+/(?:quotations|orders)/\d+(?!\w)", text))
    return {"score": int(present), "explanation": "含純文字系統連結" if present else "缺少純文字系統連結"}
