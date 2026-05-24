# CalcChain Backend Secrets API

Secrets are handled through explicit auth nodes in the graph.

The catalog descriptor for an auth node marks credential fields:

- public fields: `x-calcchain-credential: "public"`
- secret fields: `x-calcchain-credential: "secret"` or `x-calcchain-secret: true`

The frontend may use the same metadata to render secret inputs as password
fields. Secret values must not be saved in project graphs, compiled configs,
logs, events, or artifacts.

## Flow

1. The frontend sends the graph to `POST /api/secrets/requirements`.
2. The backend returns `secret_ref`, credential fields, usage, and status.
3. The frontend sends only secret values to `POST /api/secrets/session`.
4. Public values, such as `username`, stay in the graph config.
5. Graph/project save and graph compile strip secret values if they are present
   accidentally and keep only `credential_ref`.
6. Runtime backend code resolves a single secret field through
   `SecretService.resolve_value(session_key, secret_ref, field_name)`.

## Stored Value Example

```json
{
  "secret_ref": "secret:graph:...",
  "kind": "login-password",
  "values": {
    "password": "actual-password"
  }
}
```

Responses expose only field names and `has_value` flags.

## Core Mapping

When graph compilation creates a core source or target ref, it should map auth
node data like this:

```toml
[inputs.source.credentials.public]
username = "calcchain-readonly"

[inputs.source.credentials.secrets]
password = "secret:graph:..."
```

Then core asks `SecretsResolver` for key `secret:graph:...` with context name
`password`. The backend secrets adapter should call:

```python
secret_service.resolve_value(session_key, secret_ref, field_name)
```

## Current Limits

- Secrets are session-local in memory.
- Persistent keyring storage is not connected yet.
- `RunService` does not yet pass secrets into real `CalculationCore` execution.
