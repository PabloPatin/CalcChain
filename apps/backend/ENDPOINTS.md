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
Accepts a graph document and returns a build config when validation succeeds.

The current build config is a stable backend contract containing:

- schema version;
- graph digest;
- catalog version;
- graph nodes and edges;
- a topological execution plan where possible.

Later this service should be replaced or extended with a direct bridge to the CalcChain core compiler.

## Projects

### `GET /api/projects`
Returns all saved projects.

Projects are currently stored in `.calcchain_backend/projects.json`.

### `POST /api/projects`
Creates a new project with a name, optional description, and graph document.

Credentials must not be stored in the project graph. This archive intentionally does not implement credentials.

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
Creates a run from a compiled build config.

The intended UI flow is:

1. `POST /api/graphs/compile`;
2. if compile succeeds, send the returned `build_config` to `POST /api/runs`.

The current implementation starts an in-memory async run scaffold. It produces logs, SSE events, progress, and a `manifest.json` artifact. Replace `RunService._execute_run()` with the real CalcChain execution once the final core run contract is fixed.

### `GET /api/runs`
Returns a list of known runs with IDs, names, statuses, and timestamps.

### `GET /api/runs/{run_id}`
Returns detailed run state: status, progress, timestamps, build config, and error message if failed.

### `POST /api/runs/{run_id}/cancel`
Requests cancellation of a running or queued run.

The current scaffold marks the run as `cancelling` and then `cancelled` when the execution loop observes the cancellation flag.

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

The current scaffold creates `manifest.json` when a run completes successfully.

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
