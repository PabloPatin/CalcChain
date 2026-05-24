# CalcChain Backend API scaffold

Backend-only FastAPI package for CalcChain.

## Install

From repository root:

```bash
cd backend
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

The current archive includes transient secrets endpoints, but does not touch `calcchain-ui`.

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
- runs and generated demo artifacts are stored in `.calcchain_backend/runs/`.
- `POST /api/runs` currently uses a safe in-memory scaffold. Replace `RunService._execute_run()` with real calls to CalcChain core when the final build/run config contract is fixed.
- credentials are represented by auth nodes; secret values are accepted only by `/api/secrets/*` and are not stored in projects, compiled build configs, logs, events, or artifacts.
