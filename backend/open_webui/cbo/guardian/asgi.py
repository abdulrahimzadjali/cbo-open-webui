"""Guardian coverage for the direct inference routes.

``/openai/chat/completions``, ``/ollama/api/chat`` and friends accept any
verified user (a browser session token is enough, not only an API key) and go
straight to the provider without ``process_chat_payload``. Without this
middleware they are a complete bypass of the guardian.

A pure ASGI middleware (rather than edits to each upstream router) keeps the
CBO surface to one ``add_middleware`` line in ``main.py``. Internal calls from
the WebUI chat pipeline invoke those router functions directly, not over HTTP,
so they never pass through here and are not screened twice.
"""

from __future__ import annotations

import json
import logging
import re

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from open_webui.cbo.guardian.hook import REFUSAL_STATUS, screen_payload
from open_webui.cbo.guardian.settings import load_settings

log = logging.getLogger(__name__)

#: Every POST route under the provider routers that runs inference. The
#: optional ``/<n>`` suffix is the ``url_idx`` variant of the Ollama routes.
GUARDED_PATHS = re.compile(
    r'^/(?:'
    r'openai/(?:chat/completions|responses)'
    r'|ollama/(?:api/(?:chat|generate)|v1/(?:chat/completions|completions|messages|responses))'
    r')(?:/\d+)?/?$'
)


def is_guarded_path(path: str) -> bool:
    return bool(GUARDED_PATHS.match(path or ''))


class GuardianASGIMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope['type'] != 'http'
            or scope.get('method') != 'POST'
            or not is_guarded_path(scope.get('path', ''))
        ):
            await self.app(scope, receive, send)
            return

        try:
            settings = await load_settings()
        except Exception:  # noqa: BLE001 - never take the route down over config
            log.exception('Prompt Guardian: could not load settings for %s', scope.get('path'))
            await self.app(scope, receive, send)
            return

        if not settings.enabled:
            await self.app(scope, receive, send)
            return

        # Buffer the body so it can be inspected and then replayed unchanged.
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            body.extend(message.get('body', b''))
            if not message.get('more_body', False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = None  # let the route return its own validation error

        if isinstance(payload, dict):
            try:
                # Lazy import: utils.auth pulls in the whole persistence layer.
                from open_webui.utils.auth import get_optional_verified_user_from_request

                user = await get_optional_verified_user_from_request(Request(scope))
                # Unauthenticated requests fall through; the route rejects them.
                if user is not None:
                    result = await screen_payload(
                        payload, user, settings=settings, route=scope.get('path')
                    )
                    if result is not None and result.blocked:
                        response = JSONResponse(
                            {'detail': result.message}, status_code=REFUSAL_STATUS
                        )
                        await response(scope, replay, send)
                        return
            except Exception:  # noqa: BLE001
                log.exception('Prompt Guardian: screening failed for %s', scope.get('path'))
                if not settings.fail_open:
                    response = JSONResponse(
                        {'detail': 'Prompt screening is unavailable.'}, status_code=503
                    )
                    await response(scope, replay, send)
                    return

        await self.app(scope, replay, send)
