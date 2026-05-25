# CalcChain Backend API

Backend-only FastAPI package for CalcChain.

## Install

From repository root:

```bash
cd apps/backend
python -m pip install -e .
```

## Run

```bash
calcchain-backend serve --project-root ..
```

For LAN binding without authentication integration yet:

```bash
calcchain-backend serve --project-root .. --lan
```

In LAN mode the backend requires browser pairing. In another terminal on the
same machine, generate a one-time code:

```bash
calcchain-backend pair
```

Enter the 8-digit code in the frontend pairing screen. The frontend stores the
returned bearer token in `sessionStorage` and sends it with API requests.

## Test

From repository root:

```bash
uv run --project apps/backend pytest tests
```

## Package structure

```text
backend/
  pyproject.toml
  ENDPOINTS.md
  src/calcchain_backend/
    app.py
    cli.py
    settings.py
    dependencies.py
    api/
      server.py
      catalog.py
      graphs.py
      projects.py
      runs.py
      artifacts.py
      plugins.py
    schemas/
      *.py
    services/
      *.py
```

## Important notes

- `projects` are stored in `.calcchain_backend/projects.json`.
- plugin enable/disable state is stored in `.calcchain_backend/plugins_state.json`.
- plugin runtime environments are stored in `.calcchain_backend/plugin_envs/`.
- runs, core job directories, and generated artifacts are stored in `.calcchain_backend/runs/`.
- `POST /api/graphs/compile` emits CalcChain core `build_config`, `run_config`, optional `publish_config`, optional `rules_config`, and sanitized `graph_config`.
- `POST /api/runs` accepts the successful compile response as-is, writes compiled configs into a per-run core job directory, and executes `CalculationCore`.
- LAN mode protects API routes with `/api/auth/state`, `/api/auth/pair`, and bearer sessions.
- credentials are represented by auth nodes; secret values are accepted only by `/api/secrets/*` and are not stored in projects, compiled build configs, logs, events, or artifacts.
- backend session secrets are exposed to core through a `secrets:backend-session` capability.
- plugin capabilities are activated through `POST /api/plugins/runtime/reload` and passed into core runtime together with backend secrets.
