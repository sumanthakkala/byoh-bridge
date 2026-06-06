# byoh-bridge — Bring Your Own Hermes

> The reusable runtime for **BYOA apps** — software whose backend is the user's
> own local AI agent ([Hermes](https://github.com/)) and whose data never leaves
> the user's machine. `byoh-bridge` is the plumbing; you write the domain.

A traditional app is `Browser → REST API → Postgres`. A BYOA app is
`Browser → dumb relay → your local Hermes agent → local SQLite`. The "API surface"
isn't endpoints — it's **typed tools the agent calls inside scoped workflows**.
`byoh-bridge` provides all the generic machinery to make that work:

- **Outbound relay bridge** — dials a relay/gateway, speaks the `byo.*` JSON-RPC
  protocol, streams agent events back to the browser.
- **Workflow autodiscovery** — drop a folder of typed tools + read RPCs + a
  `SKILL.md`; it's wired up. Tool/RPC contracts (`Tool`, `Rpc`, `Workflow`) + a
  metric factory.
- **Local SQLite storage** — one `Base`, WAL mode, programmatic Alembic
  migrations, and **automatic change-events** (any committed write notifies the
  subscribed browser — zero per-feature code).
- **Per-session tool sandbox** — a `pre_tool_call` hook blocks any tool outside
  the active workflow's allowlist.
- **Chunked upload pipeline** into a local inbox (bytes never touch the cloud).
- **Dependency safety net** + a `/byoh-doctor` command.

## Install

```bash
# into your Hermes venv (editable, for development):
~/.hermes/hermes-agent/venv/bin/pip install -e path/to/byoh-bridge
# or, once published:
pip install byoh-bridge
```

It declares `sqlalchemy`, `alembic`, `websockets` — so installing it (or a plugin
that depends on it) pulls those in. No more hand-installing them into the venv.

## Build a plugin on it

Your whole plugin entrypoint:

```python
# my_app/__init__.py
from byoh_bridge import register as byoh_register, AppConfig

APP_CONFIG = AppConfig(
    name="my-app",                                # data-dir + default agent-id slug
    workflows_package="my_app.workflows",         # autodiscovered
    models_package="my_app.storage.models",       # imported → Base.metadata
    migrations_path=__path__[0] + "/alembic",     # you own your versions/
    # optional, env-overridable: data_dir, relay_url, agent_id,
    # extra_requirements=[...], document_store=MyDocumentStore(),
)

def register(ctx):       # Hermes calls this at startup
    byoh_register(ctx, APP_CONFIG)
```

A feature is a workflow directory:

```python
# my_app/workflows/weight/__init__.py
from pathlib import Path
from byoh_bridge.workflows import Workflow, register_tools, collect_rpcs

_SKILL = (Path(__file__).parent / "SKILL.md").read_text()

def build_workflow(ctx) -> Workflow:
    tools = register_tools(ctx, f"{__name__}.tools")     # tools/<x>.py → TOOL = Tool(...)
    return Workflow(name="weight", skill=_SKILL,
                    allowed_tools=[t.name for t in tools],
                    rpcs=collect_rpcs(f"{__name__}.rpcs"))  # rpcs/<x>.py → RPC = Rpc(...)
```

Models subclass the shared base; your `alembic/env.py` is three lines:

```python
# my_app/storage/models/weight.py
from byoh_bridge.storage import Base
from sqlalchemy.orm import Mapped, mapped_column
class WeightLog(Base):
    __tablename__ = "weight_logs"
    ...

# my_app/alembic/env.py
from my_app import APP_CONFIG
from byoh_bridge.alembic_support import run_env
run_env(APP_CONFIG)
```

## Configuration (env overrides)

| Env var | Default | Purpose |
|---|---|---|
| `BYOH_RELAY_URL` | `ws://127.0.0.1:3000/ws/agent` | Where the bridge dials |
| `BYOH_AGENT_ID` | `<app-name>-local` | Relay pairing id (must match the browser) |
| `BYOH_DATA_DIR` | `<hermes_home>/<app-name>` | Where `app.db` + `inbox/` live |
| `BYOH_BRIDGE_ENABLED` | `1` | Set `0` to load tools without dialing |

## Verify (no live Hermes needed)

```bash
# migrations against a scratch DB:
export BYOH_DATA_DIR=$(mktemp -d)
cd path/to/your-plugin && alembic upgrade head
```

## Reference app

[tinybeat](https://github.com/) — a private pregnancy companion — is the
reference plugin built on `byoh-bridge`. See `docs/byoa/` in that project for the
full architecture, security model, and framework-extraction story.

---

MIT licensed. Status: 0.1.0, pre-release.
