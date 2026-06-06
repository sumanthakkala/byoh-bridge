"""RPC definition shared across workflows.

Each RPC file in a workflow's ``rpcs/`` package exports an ``RPC``
constant of this type. The workflow's ``rpcs/__init__.py`` walks the
package and assembles a ``{method: handler}`` dict the bridge router
consults at request time.

Co-locating the method name with its handler in one dataclass means an
RPC is one file — no central registry list to keep in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Rpc:
    """One browser-callable JSON-RPC method.

    Attributes:
        method      The JSON-RPC method name. Convention:
                    ``"byo.<noun>.<verb>"`` (e.g. ``"byo.weight.list"``).
                    Dotted, never collides with tool names (tools use
                    ``^[a-zA-Z0-9_-]+$`` only).
        handler     Callable invoked with the request's ``params`` dict.
                    Returns the dict that becomes the JSON-RPC reply's
                    ``result`` field.
        description Optional human-readable summary. Surfaced by future
                    RPC introspection (e.g. a ``byo.rpcs.list`` method).
        read_only   Convention flag for "this RPC does not modify state".
                    True for everything in the POC; the architecture
                    permits write RPCs but they'd skip the audit trail
                    of going through an agent tool call.
    """

    method: str
    handler: Callable[[dict], dict]
    description: str = ""
    read_only: bool = True
