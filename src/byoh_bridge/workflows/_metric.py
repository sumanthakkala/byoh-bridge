"""Shared metric helpers (PRD-05) — factories for the common log-tool + list-RPC.

Most health metrics follow one shape: ``{recorded_at, <values…>, note?, source?,
idempotency_key}`` → idempotent insert. These factories build that tool + a list
RPC from a model + a field spec, so a metric workflow is ~15 lines.

Weight's hand-written tool stays as the readable reference. Keep this thin: a
metric needing special logic (BP zones, kick sessions) writes a normal tool —
the factory is only for the common case. Common columns (note/source/
source_report_id) are written only if the model actually has them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import desc, select

from .. import storage
from ._rpc import Rpc
from ._tool import Tool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Field:
    name: str
    type: str  # "number" | "integer" | "string"
    description: str
    required: bool = True
    # Optional allowed-value set (e.g. glucose reading_type). Surfaced in the
    # JSON schema and validated in the handler.
    enum: tuple[str, ...] | None = None


def _json_type(t: str) -> str:
    return {"number": "number", "integer": "integer", "string": "string"}.get(t, "string")


def make_log_tool(
    *,
    name: str,
    model: type,
    fields: list[Field],
    description: str,
    emoji: str = "",
    toolset: str = "hermes-cli",
) -> Tool:
    """Build an idempotent insert tool for a metric model."""
    props: dict = {
        "recorded_at": {
            "type": "string",
            "description": "Date or ISO timestamp (YYYY-MM-DD or full ISO 8601).",
        },
    }
    required = ["recorded_at"]
    for f in fields:
        props[f.name] = {"type": _json_type(f.type), "description": f.description}
        if f.enum:
            props[f.name]["enum"] = list(f.enum)
        if f.required:
            required.append(f.name)
    if hasattr(model, "note"):
        props["note"] = {"type": "string", "description": "Optional free-text note."}
    if hasattr(model, "source"):
        props["source"] = {
            "type": "string",
            "description": "Where the value came from: self | report | device (default self).",
        }
    props["idempotency_key"] = {"type": "string", "description": "Stable de-dupe key. Required."}
    required.append("idempotency_key")

    schema = {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": props, "required": required, "additionalProperties": False},
    }

    def handler(args: dict[str, Any], **_: Any) -> str:
        recorded_at = str(args.get("recorded_at", "")).strip()
        key = str(args.get("idempotency_key", "")).strip()
        if not recorded_at or not key:
            return json.dumps({"ok": False, "error": "recorded_at and idempotency_key required"})

        values: dict[str, Any] = {"recorded_at": recorded_at, "idempotency_key": key}
        for f in fields:
            v = args.get(f.name)
            if v is None:
                if f.required:
                    return json.dumps({"ok": False, "error": f"{f.name} required"})
                continue
            if f.type == "number":
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return json.dumps({"ok": False, "error": f"{f.name} must be a number"})
            elif f.type == "integer":
                try:
                    v = int(v)
                except (TypeError, ValueError):
                    return json.dumps({"ok": False, "error": f"{f.name} must be an integer"})
            if f.enum and v not in f.enum:
                return json.dumps({"ok": False, "error": f"{f.name} must be one of {list(f.enum)}"})
            values[f.name] = v
        if hasattr(model, "note") and args.get("note") is not None:
            values["note"] = args.get("note")
        if hasattr(model, "source") and args.get("source"):
            values["source"] = args.get("source")
        if hasattr(model, "source_report_id") and args.get("source_report_id"):
            values["source_report_id"] = args.get("source_report_id")

        with storage.session() as s:
            existing = s.scalar(select(model).where(model.idempotency_key == key))
            if existing is not None:
                return json.dumps({"ok": True, "id": existing.id, "deduped": True})
            row = model(**values)
            s.add(row)
            s.flush()
            row_id = row.id
        logger.info("[%s] logged id=%s", name, row_id)
        return json.dumps({"ok": True, "id": row_id})

    return Tool(name=name, toolset=toolset, schema=schema, handler=handler, description=description, emoji=emoji)


def make_list_rpc(
    *,
    method: str,
    model: type,
    serialize: Callable[[Any], dict],
    description: str = "",
    default_limit: int = 50,
) -> Rpc:
    """Build a 'most recent N rows' read RPC for a metric model."""

    def handler(params: dict) -> dict:
        limit = int(params.get("limit", default_limit) or default_limit)
        with storage.session() as s:
            rows = (
                s.execute(select(model).order_by(desc(model.recorded_at), desc(model.id)).limit(limit))
                .scalars()
                .all()
            )
            payload = [serialize(r) for r in rows]
        return {"rows": payload, "count": len(payload)}

    return Rpc(method=method, handler=handler, description=description or f"List rows for {method}", read_only=True)
