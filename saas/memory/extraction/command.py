"""Explicit command extraction: ``/记住 ...`` with optional tags/kind/importance."""

from __future__ import annotations

import re

from ..models import KIND_LABELS, MemoryDraft, Turn

_REMEMBER = re.compile(
    r"^\s*[/／]?(?:记住|remember|记下)\s*[:：]?\s*(?P<body>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_TAG = re.compile(r"(?:#|＃)([\w\u4e00-\u9fff-]{1,32})")
_KIND = re.compile(r"(?:kind|类型)\s*[:：]\s*(fact|preference|event|note)", re.IGNORECASE)
_IMPORTANCE = re.compile(r"(?:importance|重要度)\s*[:：]\s*([1-5])")


class CommandExtractor:
    async def extract(self, turns: list[Turn], *, max_items: int = 3) -> list[MemoryDraft]:
        drafts: list[MemoryDraft] = []
        for turn in turns:
            if turn.role not in {"user", "system"}:
                continue
            match = _REMEMBER.match(turn.content or "")
            if not match:
                continue
            body = match.group("body")
            tags = _TAG.findall(body)
            kind_match = _KIND.search(body)
            importance_match = _IMPORTANCE.search(body)
            content = _TAG.sub("", _KIND.sub("", _IMPORTANCE.sub("", body))).strip()
            content = re.sub(r"\s{2,}", " ", content).strip(" ,，。;；")
            if not content:
                continue
            kind = (kind_match.group(1).lower() if kind_match else "fact")
            if kind not in KIND_LABELS:
                kind = "fact"
            drafts.append(
                MemoryDraft(
                    content=content[:4000],
                    kind=kind,
                    importance=int(importance_match.group(1)) if importance_match else 3,
                    tags=[tag for tag in tags if tag],
                    source_conversation_id=turn.conversation_id,
                    source_message_id=turn.message_id,
                )
            )
            if len(drafts) >= max_items:
                break
        return drafts
