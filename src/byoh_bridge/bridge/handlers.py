"""Built-in ``byo.*`` method handlers.

This module owns the *session lifecycle* surface that the bridge needs:

- ``byo.workflows.list``  — what workflows exist?
- ``byo.agent.status``    — am I online?
- ``byo.session.start``   — create a new tui_gateway session for one browser tab
- ``byo.session.send``    — submit a user message into that session
- ``byo.session.close``   — tear down

Workflow-defined RPCs (``byo.weight.list`` etc.) are routed by the
``FrameRouter`` to the workflow registry, *not* through here.

Each handler returns either ``{"result": ...}`` or
``{"error": {"code": int, "message": str}}``.
"""

from __future__ import annotations

import logging
from typing import Callable

from .. import storage
from ..app_config import active
from ..workflows.registry import WorkflowRegistry
from . import gateway
from .sessions import BridgeSession, SessionRegistry
from .subscriptions import SubscriptionRegistry
from .transport import BridgeTransport
from .uploads import CHUNK_SIZE, UploadRegistry

logger = logging.getLogger(__name__)

# Handler signature: (browser_session, params) -> response dict
ByoHandler = Callable[[str, dict], dict]


# ── Public factory ────────────────────────────────────────────────────────


def make_handlers(
    sessions: SessionRegistry,
    workflows: WorkflowRegistry,
    send_upstream: Callable[[dict], None],
    subscriptions: "SubscriptionRegistry",
    uploads: "UploadRegistry",
) -> dict[str, ByoHandler]:
    """Build the byo.* method handler map.

    Closes over the registries/``send_upstream`` so the returned handlers are
    self-contained.
    """
    return {
        "byo.workflows.list": _make_workflows_list(workflows),
        "byo.agent.status": _make_agent_status(),
        "byo.session.start": _make_session_start(sessions, workflows, send_upstream),
        "byo.session.send": _make_session_send(sessions),
        "byo.session.close": _make_session_close(sessions, subscriptions),
        "byo.db.subscribe": _make_db_subscribe(subscriptions),
        "byo.db.unsubscribe": _make_db_unsubscribe(subscriptions),
        "byo.file.upload_begin": _make_upload_begin(uploads),
        "byo.file.upload_chunk": _make_upload_chunk(uploads),
        "byo.file.upload_commit": _make_upload_commit(uploads),
        "byo.file.process": _make_file_process(sessions, workflows, send_upstream),
    }


# ── Handler factories ─────────────────────────────────────────────────────


def _make_workflows_list(workflows: WorkflowRegistry) -> ByoHandler:
    def handler(_browser_session: str, _params: dict) -> dict:
        return {
            "result": {
                "workflows": [
                    {
                        "name": name,
                        "allowed_tools": wf.allowed_tools,
                        "schema_version": wf.schema_version,
                        "tool_version": wf.tool_version,
                    }
                    for name, wf in workflows.items()
                ],
            },
        }

    return handler


def _make_agent_status() -> ByoHandler:
    def handler(_browser_session: str, _params: dict) -> dict:
        return {"result": {"agent_id": active().agent_id, "status": "online"}}

    return handler


def _make_session_start(
    sessions: SessionRegistry,
    workflows: WorkflowRegistry,
    send_upstream: Callable[[dict], None],
) -> ByoHandler:
    def handler(browser_session: str, params: dict) -> dict:
        workflow_name = str(params.get("workflow") or "")
        wf = workflows.get(workflow_name)
        if wf is None:
            return _error(4040, f"unknown workflow: {workflow_name}")

        transport = BridgeTransport(send_upstream, browser_session)
        resp = gateway.call(
            "session.create",
            {"cols": int(params.get("cols", 100))},
            transport,
        )
        if not resp or "result" not in resp:
            return _error(5002, f"session.create failed: {resp}")

        tui_sid = resp["result"]["session_id"]
        sessions.add(
            BridgeSession(
                browser_session=browser_session,
                tui_session_id=tui_sid,
                transport=transport,
                workflow=workflow_name,
                allowed_tools=list(wf.allowed_tools),
                primed_skill=wf.skill,
            )
        )
        return {
            "result": {
                "browser_session": browser_session,
                "tui_session_id": tui_sid,
                "workflow": workflow_name,
                "allowed_tools": wf.allowed_tools,
                "info": resp["result"].get("info"),
            },
        }

    return handler


def _make_session_send(sessions: SessionRegistry) -> ByoHandler:
    def handler(browser_session: str, params: dict) -> dict:
        sess = sessions.get(browser_session)
        if sess is None:
            return _error(4041, "no session; call byo.session.start first")

        user_text = str(params.get("text") or "")
        if not user_text:
            return _error(4002, "text required")

        prompt_text = _build_prompt(sess, user_text)
        # SKILL is only prepended on the first turn.
        sess.primed_skill = None

        resp = gateway.call(
            "prompt.submit",
            {"session_id": sess.tui_session_id, "text": prompt_text},
            sess.transport,
        )
        if resp is None:
            # Long-running handler — events stream asynchronously via transport.
            return {"result": {"status": "streaming"}}
        if "result" in resp:
            return {"result": resp["result"]}
        return _error(5003, str(resp.get("error", "prompt.submit failed")))

    return handler


def _make_session_close(sessions: SessionRegistry, subscriptions: SubscriptionRegistry) -> ByoHandler:
    def handler(browser_session: str, _params: dict) -> dict:
        # A browser closing also drops its db subscriptions (sent by the relay
        # on disconnect), so we don't leak interest for a gone tab.
        subscriptions.drop(browser_session)
        sess = sessions.pop(browser_session)
        if sess is None:
            return {"result": {"closed": False, "reason": "no such session"}}
        try:
            gateway.call(
                "session.close",
                {"session_id": sess.tui_session_id},
                sess.transport,
            )
        except Exception as exc:
            logger.warning(
                "[bridge] session.close for browser=%s failed: %s",
                browser_session, exc,
            )
        return {"result": {"closed": True}}

    return handler


def _make_db_subscribe(subscriptions: SubscriptionRegistry) -> ByoHandler:
    def handler(browser_session: str, params: dict) -> dict:
        tables = [str(t) for t in (params.get("tables") or [])]
        subscriptions.set(browser_session, tables)  # replace semantics
        return {"result": {"subscribed": tables}}

    return handler


def _make_db_unsubscribe(subscriptions: SubscriptionRegistry) -> ByoHandler:
    def handler(browser_session: str, _params: dict) -> dict:
        subscriptions.drop(browser_session)
        return {"result": {"unsubscribed": True}}

    return handler


# ── File upload + passive ingestion (PRD-07) ───────────────────────────────


def _make_upload_begin(uploads: UploadRegistry) -> ByoHandler:
    def handler(_browser_session: str, params: dict) -> dict:
        try:
            inbox_id = uploads.begin(
                str(params.get("filename") or "file"),
                str(params.get("mime") or ""),
                int(params.get("size") or 0),
            )
        except Exception as exc:
            return _error(4005, str(exc))
        return {"result": {"inbox_id": inbox_id, "chunk_size": CHUNK_SIZE}}

    return handler


def _make_upload_chunk(uploads: UploadRegistry) -> ByoHandler:
    def handler(_browser_session: str, params: dict) -> dict:
        try:
            received = uploads.chunk(
                str(params.get("inbox_id") or ""),
                int(params.get("seq") or 0),
                str(params.get("data") or ""),
            )
        except Exception as exc:
            return _error(4006, str(exc))
        return {"result": {"received": received}}

    return handler


def _make_upload_commit(uploads: UploadRegistry) -> ByoHandler:
    def handler(_browser_session: str, params: dict) -> dict:
        try:
            meta = uploads.commit(str(params.get("inbox_id") or ""), params.get("sha256"))
        except Exception as exc:
            return _error(4007, str(exc))
        # The DB row that represents a document is domain-specific — the app's
        # DocumentStore persists it (and any byo.db.changed fires automatically).
        # With no store, the bytes still land in the inbox; we just skip the row.
        store = active().document_store
        doc_id = meta["inbox_id"]
        if store is not None:
            with storage.session() as s:
                doc_id = store.on_committed(s, meta, params)
        return {"result": {"document_id": doc_id, "path": meta["path"]}}

    return handler


def _make_file_process(
    sessions: SessionRegistry,
    workflows: WorkflowRegistry,
    send_upstream: Callable[[dict], None],
) -> ByoHandler:
    def handler(browser_session: str, params: dict) -> dict:
        doc_id = str(params.get("document_id") or params.get("inbox_id") or "")
        workflow_name = str(params.get("workflow") or "")
        wf = workflows.get(workflow_name)
        if wf is None:
            return _error(4040, f"unknown workflow: {workflow_name}")
        store = active().document_store
        if store is None:
            return _error(4043, "no document store configured for this app")
        doc = store.resolve(doc_id)
        path = doc.get("path") if doc else None
        mime = doc.get("mime") if doc else None
        if not path:
            return _error(4042, "unknown document")

        transport = BridgeTransport(send_upstream, browser_session)
        resp = gateway.call("session.create", {"cols": 100}, transport)
        if not resp or "result" not in resp:
            return _error(5002, f"session.create failed: {resp}")
        tui_sid = resp["result"]["session_id"]
        sessions.add(
            BridgeSession(
                browser_session=browser_session,
                tui_session_id=tui_sid,
                transport=transport,
                workflow=workflow_name,
                allowed_tools=list(wf.allowed_tools),
                primed_skill=wf.skill,
            )
        )
        with storage.session() as s:
            store.set_status(s, doc_id, "processing")

        sess = sessions.get(browser_session)
        text = f"A file has been uploaded to {path} (document_id={doc_id}, mime={mime}). Process it following the instructions."
        prompt = _build_prompt(sess, text) if sess else text
        if sess:
            sess.primed_skill = None
        gateway.call("prompt.submit", {"session_id": tui_sid, "text": prompt}, transport)
        return {"result": {"session_id": tui_sid, "document_id": doc_id}}

    return handler


# ── Helpers ───────────────────────────────────────────────────────────────


def _build_prompt(sess: BridgeSession, user_text: str) -> str:
    """Compose the first-turn prompt envelope with SKILL + allowlist hint.

    The allowlist hint is a *soft* nudge so the model rarely reaches for
    out-of-workflow tools. Hard enforcement lives in ``bridge/policy.py``: a
    ``pre_tool_call`` hook BLOCKS any tool outside the session's allowlist
    (PRD-06). We keep the hint because Hermes 0.15.1's ``pre_llm_call`` is
    context-injection only — it can't filter the tool *definitions* the model
    sees, so def-level invisibility isn't available (candidate upstream
    contribution; MASTER-PLAN §9). Soft hint + hard block = belt and suspenders.
    """
    if not sess.primed_skill:
        return user_text
    allowed = ", ".join(sess.allowed_tools)
    return (
        f"<workflow_instructions>\n{sess.primed_skill.strip()}\n</workflow_instructions>\n\n"
        f"<scoped_tool_allowlist>\n"
        f"Only call tools in this list, even if other tools appear available: {allowed}\n"
        f"</scoped_tool_allowlist>\n\n"
        f"User: {user_text}"
    )


def _error(code: int, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
