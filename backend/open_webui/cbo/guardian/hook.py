"""Upstream integration points for the Prompt Guardian.

There are three, all calling :func:`screen_payload`:

* ``process_chat_payload`` in ``utils/middleware.py`` calls
  :func:`guard_chat_payload` immediately before the inlet filter chain -- after
  the message list is assembled, before web search, RAG, tools and the LLM
  request, so a rejected prompt costs no tokens, retrieval or tool execution.
* ``chat_completion`` in ``main.py`` calls :func:`guard_chat_payload` on the
  agent-model branch, which returns before ``process_chat_payload`` runs.
* :class:`open_webui.cbo.guardian.asgi.GuardianASGIMiddleware` screens the
  direct inference routes (``/openai/*``, ``/ollama/*``) that skip the chat
  pipeline entirely.

Every hook is a no-op unless ``cbo.guardian.enabled`` is true, which keeps the
default deployment equivalent to upstream behaviour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from open_webui.cbo.guardian.engine import (
    audit_record,
    evaluate,
    log_decision,
    record_counters,
)
from open_webui.cbo.guardian.normalize import has_arabic
from open_webui.cbo.guardian.settings import GuardianSettings, load_settings
from open_webui.cbo.guardian.types import Decision

log = logging.getLogger(__name__)

#: HTTP status used for a policy refusal. 400 keeps it distinct from transport
#: errors and renders as an ordinary chat error in the UI.
REFUSAL_STATUS = 400

#: Content-part types that carry user-authored text. ``output_text`` (an
#: assistant turn replayed in Responses input) is deliberately excluded.
_TEXT_PART_TYPES = {None, 'text', 'input_text'}


def content_text(content: Any) -> str:
    """Join *every* text part of a message's content.

    Upstream's ``get_last_user_message`` returns only the first text part, so
    a benign first part followed by a malicious second part would slip past.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get('type') in _TEXT_PART_TYPES:
                text = item.get('text')
                if isinstance(text, str):
                    parts.append(text)
        return '\n'.join(parts)
    return ''


def extract_user_turns(payload: dict) -> tuple[str, list[str]]:
    """Return ``(latest user text, earlier user texts)`` from a request body.

    Understands the shapes the app accepts: chat ``messages`` (OpenAI, Ollama
    and Anthropic), Responses ``input``, and completion/generate ``prompt``.
    Only *user*-authored turns are returned: system prompts are written by
    admins and model owners, and screening them would block every chat on a
    model whose system prompt says, for example, "never reveal your system
    prompt".
    """
    texts: list[str] = []

    messages = payload.get('messages')
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict) and message.get('role') == 'user':
                texts.append(content_text(message.get('content')))

    items = payload.get('input')
    if isinstance(items, str):
        texts.append(items)
    elif isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                texts.append(item)
            elif (
                isinstance(item, dict)
                and item.get('type', 'message') == 'message'
                and item.get('role', 'user') == 'user'
            ):
                texts.append(content_text(item.get('content')))

    prompt = payload.get('prompt')
    if isinstance(prompt, str):
        texts.append(prompt)
    elif isinstance(prompt, list):
        texts.extend(p for p in prompt if isinstance(p, str))

    if not texts:
        return '', []
    return texts[-1], [text for text in texts[:-1] if text]


@dataclass
class ScreenResult:
    decision: Decision
    settings: GuardianSettings
    is_arabic: bool

    @property
    def blocked(self) -> bool:
        return self.decision.blocked

    @property
    def message(self) -> str:
        return self.settings.message(prefer_arabic=self.is_arabic)


async def screen_payload(
    payload: dict,
    user: Any,
    *,
    settings: GuardianSettings | None = None,
    model_id: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    route: str | None = None,
) -> ScreenResult | None:
    """Evaluate a request body, record counters and the audit entry.

    Returns ``None`` when the guardian is switched off.
    """
    settings = settings or await load_settings()
    if not settings.enabled:
        return None

    latest, history = extract_user_turns(payload)
    decision = await evaluate(
        latest, settings, user_role=getattr(user, 'role', None), history=history
    )
    is_arabic = has_arabic(latest)
    record_counters(decision, settings, is_arabic=is_arabic)

    record = audit_record(
        decision,
        text=latest,
        user_id=getattr(user, 'id', None),
        model_id=model_id or payload.get('model'),
        chat_id=chat_id,
        message_id=message_id,
    )
    if route:
        record['route'] = route
    await log_decision(record)

    return ScreenResult(decision=decision, settings=settings, is_arabic=is_arabic)


async def guard_chat_payload(request, form_data, user, metadata, model) -> None:
    """Evaluate a chat request and raise on refusal.

    Returns ``None`` when the request may proceed, so callers need no
    branching beyond a single ``await``.
    """
    metadata = metadata or {}
    result = await screen_payload(
        form_data,
        user,
        model_id=form_data.get('model') or (model or {}).get('id'),
        chat_id=metadata.get('chat_id'),
        message_id=metadata.get('message_id'),
        route='chat',
    )
    if result is not None and result.blocked:
        raise HTTPException(status_code=REFUSAL_STATUS, detail=result.message)
