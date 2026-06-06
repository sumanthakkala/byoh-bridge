"""In-progress upload transfers → the local inbox (PRD-07).

Streams chunked, base64-encoded file data to disk under ``inbox/``. Server-side
validation (mime allowlist, 25 MB cap) and a controlled on-disk name
(``<inbox_id>.<ext>``, never the user's filename) prevent oversized/typed/traversal
abuse. The relay only routes these frames — it never sees or keeps the bytes.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
from dataclasses import dataclass
from typing import IO, Optional

from .. import storage

logger = logging.getLogger(__name__)

MAX_SIZE = 25 * 1024 * 1024  # 25 MB
CHUNK_SIZE = 256 * 1024

# mime → extension allowlist (v1).
MIME_EXT = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/heic": "heic",
    "image/heif": "heif",
    "text/plain": "txt",
}


@dataclass
class _Transfer:
    inbox_id: str
    filename: str
    mime: str
    size: int
    ext: str
    fh: IO[bytes]
    received: int = 0
    next_seq: int = 0


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class UploadRegistry:
    def __init__(self) -> None:
        self._t: dict[str, _Transfer] = {}
        self._lock = threading.Lock()

    def begin(self, filename: str, mime: str, size: int) -> str:
        if mime not in MIME_EXT:
            raise ValueError(f"unsupported file type: {mime or '(none)'}")
        if size <= 0 or size > MAX_SIZE:
            raise ValueError(f"file too large (max {MAX_SIZE // (1024 * 1024)} MB)")
        inbox_id = "doc_" + secrets.token_hex(8)
        part = storage.inbox_dir() / f"{inbox_id}.part"
        fh = open(part, "wb")
        with self._lock:
            self._t[inbox_id] = _Transfer(inbox_id, filename, mime, size, MIME_EXT[mime], fh)
        return inbox_id

    def chunk(self, inbox_id: str, seq: int, data_b64: str) -> int:
        with self._lock:
            t = self._t.get(inbox_id)
        if t is None:
            raise ValueError("unknown upload")
        if seq != t.next_seq:
            raise ValueError(f"out-of-order chunk (expected {t.next_seq}, got {seq})")
        raw = base64.b64decode(data_b64)
        if t.received + len(raw) > MAX_SIZE:
            self.abort(inbox_id)
            raise ValueError("exceeds size cap")
        t.fh.write(raw)
        t.received += len(raw)
        t.next_seq += 1
        return t.received

    def commit(self, inbox_id: str, sha256: Optional[str] = None) -> dict:
        with self._lock:
            t = self._t.pop(inbox_id, None)
        if t is None:
            raise ValueError("unknown upload")
        t.fh.close()
        part = storage.inbox_dir() / f"{inbox_id}.part"
        digest = _sha256(part)
        if sha256 and sha256 != digest:
            part.unlink(missing_ok=True)
            raise ValueError("checksum mismatch")
        final = storage.inbox_dir() / f"{inbox_id}.{t.ext}"
        part.rename(final)
        return {
            "inbox_id": inbox_id,
            "filename": t.filename,
            "mime": t.mime,
            "size_bytes": final.stat().st_size,
            "sha256": digest,
            "path": str(final),
            "ext": t.ext,
        }

    def abort(self, inbox_id: str) -> None:
        with self._lock:
            t = self._t.pop(inbox_id, None)
        if t is not None:
            try:
                t.fh.close()
            except Exception:
                pass
            (storage.inbox_dir() / f"{inbox_id}.part").unlink(missing_ok=True)
