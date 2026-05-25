# CalcChain Backend API endpoints

This file describes the backend endpoints included in this archive. The API is split by responsibility: server state, catalog, graph operations, projects, runs, artifacts, and plugins.

## Server

### `GET /api/server/info`
Returns basic backend information: application name, backend package version, API version, current mode, and whether authentication is required.

Use it on frontend startup to check that the browser is connected to a CalcChain backend, not to a random service on the same port.

### `GET /api/server/health`
Simple healthcheck endpoint. Returns `{"status":"ok"}` when the backend process is alive.

Use it for diagnostics and lightweight connectivity checks.

## Catalog

### `GET /api/catalog`
Returns the UI catalog: block descriptors, port kinds, connection rules, catalog version, and enabled plugin IDs.

The frontend should eventually build its block palette from this response instead of hardcoding block types.

### `GET /api/catalog/connection-rules`
Returns only connection rules.

Use it when the frontend needs to refresh compatibility logic without reloading the whole catalog.

## Graphs

### `POST /api/graphs/validate`
Accepts a graph document and validates it against the current catalog.

The endpoint checks:

- unknown block types;
- missing required config fields;
- edges pointing to missing nodes or ports;
- output/input direction mistakes;
- port-kind compatibility;
- required connections;
- maximum input connection count;
- isolated nodes as warnings.

Use it for a `Validate` button and for highlighting graph errors in the UI.

### `POST /api/graphs/compile`
Accepts a graph document and returns core configs when validation succeeds.

The response contains:

- `build_config`: CalcChain core `BuildConfig`;
- `run_config`: CalcChain core `RunConfig`;
- `publish_config`: CalcChain core `PublishConfig` when publish targets exist;
- `rules_config`: CalcChain core `RulesFile` when build or publish rules are needed;
- `graph_config`: sanitized graph metadata, graph digest, catalog version, graph nodes and edges, and a topological execution plan.

Secret field values are stripped from `graph_config` and are never copied into core configs. Core configs receive only `credentials.secrets` references.

## Projects

### `GET /api/projects`
Returns all saved projects.

Projects are currently stored in `.calcchain_backend/projects.json`.

### `POST /api/projects`
Creates a new project with a name, optional description, and graph document.

Secret credential values are stripped before the graph is stored. Projects keep public credential values and secret references only.

### `GET /api/projects/{project_id}`
Returns one project by ID.

Returns `404` if the project does not exist.

### `PUT /api/projects/{project_id}`
Updates project name, description, and/or graph.

Returns the updated project or `404` if the project does not exist.

### `DELETE /api/projects/{project_id}`
Deletes a project.

Returns `204 No Content` on success or `404` if the project does not exist.

## Runs

### `POST /api/runs`
Creates a run from compiled core configs and executes it with `CalculationCore`.

The intended UI flow is:

1. `POST /api/graphs/compile`;
2. store required secret values through `/api/secrets/session`;
3. if compile succeeds, send the compile response to `POST /api/runs`.

Request fields:

- `build_config`: required CalcChain core `BuildConfig`;
- `run_config`: optional CalcChain core `RunConfig`; when omitted, backend performs build only;
- `publish_config`: optional CalcChain core `PublishConfig`; when present, backend publishes after run/build;
- `rules_config`: optional CalcChain core `RulesFile`, written as `rules.json`;
- `graph_config`: optional sanitized graph metadata, written as `graph.json`;
- `run_options`: backend options such as display `name`.

`POST /api/runs` accepts the successful `/api/graphs/compile` response as-is. It ignores `diagnostics` and `warnings`; if `valid` is explicitly `false`, it returns `400`.

The backend creates a per-run job directory under `.calcchain_backend/runs/{run_id}/job`, writes core config files, creates and validates the build lock, materializes the working directory, runs the process, optionally publishes, and exposes selected core artifacts through the artifacts endpoints.

## LAN Auth

When the backend runs in LAN mode, API routes except `/api/server/*` and `/api/auth/*` require a bearer session token.

### `GET /api/auth/state`

Returns:

- `auth_required`: whether pairing/session auth is enabled;
- `authenticated`: whether the current bearer token is valid.

### `POST /api/auth/pair`

Accepts an 8-digit one-time pairing code:

```json
{
  "code": "12345678"
}
```

Returns a bearer token. The frontend stores this token and sends it as `Authorization: Bearer <token>`.

### `POST /api/auth/logout`

Revokes the current bearer token.

Pairing codes are generated through the local-only control socket:

```bash
calcchain-backend pair
```

The control socket is bound to `127.0.0.1` and protected by a per-process secret in the user profile. It is not exposed over the LAN HTTP API.

### `GET /api/runs`
Returns a list of known runs with IDs, names, statuses, and timestamps.

### `GET /api/runs/{run_id}`
Returns detailed run state: status, progress, timestamps, build config, and error message if failed.

### `POST /api/runs/{run_id}/cancel`
Requests cancellation of a running or queued run.

Cancellation is observed between core phases and by the core process runner while a command is running.

### `GET /api/runs/{run_id}/events`
Streams run events using Server-Sent Events.

Events include:

- `run_queued`;
- `run_started`;
- `step_started`;
- `progress`;
- `run_finished`;
- `run_cancelled`;
- `run_failed`.

Use this for live progress updates in the UI.

### `GET /api/runs/{run_id}/logs`
Returns accumulated log items for a run.

Use it both after completion and as a fallback if SSE is unavailable.

## Artifacts

### `GET /api/runs/{run_id}/artifacts`
Returns artifact metadata for a run.

Typical artifacts include `manifest.json`, `run.json`, core config/lock files, `runtime_status.json`, and process `stdout.txt`/`stderr.txt` logs when available.

### `GET /api/runs/{run_id}/artifacts/{artifact_id}`
Downloads a run artifact as a file.

Use this for full result files, not for inline previews.

### `GET /api/runs/{run_id}/artifacts/{artifact_id}/preview`
Returns a JSON/text preview for small supported artifacts.

Large files and binary files return an `unsupported` preview response.

## Plugins

### `GET /api/plugins`
Scans `plugins/*/plugin.json` under the CalcChain project root and returns plugin descriptors, enabled/disabled state, capabilities, entrypoints, and restart flags.

The SVN plugin descriptor is expected to expose source and target capabilities.

### `PATCH /api/plugins/{plugin_id}`
Updates plugin enabled state.

Request body:

```json
{
  "enabled": false
}
```

The endpoint writes state to `.calcchain_backend/plugins_state.json` and returns `restart_required: true`. Hot plugin unload/reload is intentionally not implemented in the MVP because plugins affect catalog, validation, compilation, and running calculations.

### `GET /api/plugins/runtime/status`

Returns current plugin runtime state: whether runtime capabilities are active,
active plugin IDs, registered capabilities, diagnostics, and the last activation
error.

### `POST /api/plugins/runtime/reload`

Discovers enabled plugins, verifies/install their wheel-based dependencies into
`.calcchain_backend/plugin_envs`, imports plugin entrypoints, and builds
`RuntimeCapabilities` for core. Use this after changing plugin enabled state.

The runtime is cached by the backend process. Core execution receives this
runtime plus the backend session secrets capability.

## Credentials note

Credentials are represented by explicit auth nodes in the graph. Auth node descriptors come from the catalog, including plugins. A descriptor marks public credential fields with `x-calcchain-credential: "public"` and secret fields with `x-calcchain-credential: "secret"` or `x-calcchain-secret: true`.

Secret values must not be stored in the project graph, compiled core configs, logs, events, or artifacts. The frontend sends secret values only to the secrets API. Core configs receive only secret references in `credentials.secrets`.

---

# Secrets endpoints

## `POST /api/secrets/requirements`

Accepts a `graph` or a compiled `build_config` containing graph nodes and edges. Returns auth requirements discovered from catalog descriptors:

- `secret_ref`: the key that will be written to core `credentials.secrets`;
- `fields`: public and secret credential fields;
- `used_by`: auth node and connected source/target nodes;
- `status`: `missing`, `partial`, or `satisfied` for the current backend session.

The response never contains secret values.

## `GET /api/secrets/session`

Returns stored secret status for the current backend session. It returns field names and `has_value` flags only, not values or previews.

## `POST /api/secrets/session`

Stores secret field values for the current backend session. The frontend should send values using the `secret_ref` returned by `/requirements`.

Example:

```json
{
  "secret_ref": "secret:graph:...",
  "kind": "login-password",
  "values": {
    "password": "plain value entered by user"
  }
}
```

Public fields such as `username` remain in the graph config and are not stored in the secret store.

## `DELETE /api/secrets/session/{secret_ref}`

Deletes one stored secret from the current backend session.

## `POST /api/secrets/session/clear`

Deletes all stored secrets for the current backend session. Intended for logout or `Forget credentials`.
