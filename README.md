# byoh-bridge — Bring Your Own Hermes

> The reusable runtime for **BYOH apps** — software whose backend is the user's
> own local AI agent ([Hermes](https://github.com/)) and whose data never leaves
> the user's machine. `byoh-bridge` is the plumbing; you write the domain.

A traditional app is `Browser → REST API → Postgres`. A BYOH app is
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
# from PyPI (the normal way):
pip install byoh-bridge
# …or straight into your Hermes venv:
~/.hermes/hermes-agent/venv/bin/pip install byoh-bridge
# …or editable, for hacking on the framework itself:
~/.hermes/hermes-agent/venv/bin/pip install -e path/to/byoh-bridge
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

## Loading a plugin into Hermes (today's gotcha)

Hermes (≤ 0.15.x) discovers plugins as **flat directories** and loads each
plugin's **root `__init__.py` by path**, calling `register(ctx)`. It does **not**
`pip install` the plugin or its dependencies. That clashes with the clean,
distributable shape this framework encourages — a **src-layout pip package**
using absolute imports (`from byoh_bridge import …`, an `AppConfig.models_package`
like `"my_app.storage.models"`). A bare clone therefore won't run: Hermes finds
no `register()` at the directory root, and neither your package nor `byoh-bridge`
is importable in Hermes's venv.

Until Hermes supports installed-package / entry-point plugin discovery (tracked
in `docs/byoh/03-HERMES-GAPS.md`), reconcile it two ways:

1. **A root `__init__.py` shim** committed at your plugin repo root — Hermes loads
   this by path and it delegates to your real package:
   ```python
   # <plugin-repo>/__init__.py
   from my_app import APP_CONFIG, register  # noqa: F401
   ```
   With a `src/` layout, setuptools ignores this root file, so it never lands in
   your wheel.
2. **`pip install` the plugin** into Hermes's venv (so the package + `byoh-bridge`
   + SQLAlchemy/Alembic resolve). `hermes plugins install owner/repo` only
   *clones* — follow it with `pip install <cloned-dir>`.

The reference plugin
[`tinybeat-pregnancy`](https://github.com/sumanthakkala/tinybeat-pregnancy) does
exactly this — its README has the copy-paste commands.

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

[tinybeat-pregnancy](https://github.com/sumanthakkala/tinybeat-pregnancy) — the
plugin behind a private pregnancy companion — is the reference app built on
`byoh-bridge`: 11 workflows, domain models + migrations + safety, wired by one
`AppConfig`. It's the worked example of everything above.

---

MIT licensed. Status: 0.1.0, pre-release.
