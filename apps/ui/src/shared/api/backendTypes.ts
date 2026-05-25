export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export type DiagnosticSeverity = 'error' | 'warning' | 'info';

export type Diagnostic = {
  code: string;
  message: string;
  severity: DiagnosticSeverity;
  node_id?: string | null;
  port_id?: string | null;
  edge_id?: string | null;
  details: JsonObject;
};

export type ServerInfo = {
  app: string;
  version: string;
  api_version: string;
  mode: string;
  auth_required: boolean;
};

export type HealthResponse = {
  status: 'ok';
};

export type AuthState = {
  auth_required: boolean;
  authenticated: boolean;
};

export type PairingResponse = {
  token: string;
  token_type: 'bearer';
  expires_in_seconds: number;
};

export type PortDirection = 'input' | 'output';

export type BackendPortDescriptor = {
  id: string;
  title: string;
  direction: PortDirection;
  kind: string;
  required: boolean;
  max_connections?: number | null;
};

export type BackendBlockDescriptor = {
  type: string;
  title: string;
  category: string;
  description?: string | null;
  ports: BackendPortDescriptor[];
  config_schema: JsonObject;
  plugin_id?: string | null;
};

export type ConnectionRule = {
  id: string;
  from_kind: string;
  to_kind: string;
  description?: string | null;
};

export type CatalogResponse = {
  catalog_version: string;
  port_kinds: string[];
  blocks: BackendBlockDescriptor[];
  connection_rules: ConnectionRule[];
  plugins: string[];
};

export type BackendGraphPosition = {
  x: number;
  y: number;
};

export type BackendGraphNode = {
  id: string;
  type: string;
  title?: string | null;
  position?: BackendGraphPosition | null;
  config: JsonObject;
};

export type BackendGraphEdgeEndpoint = {
  node_id: string;
  port_id: string;
};

export type BackendGraphEdge = {
  id: string;
  source: BackendGraphEdgeEndpoint;
  target: BackendGraphEdgeEndpoint;
};

export type BackendGraphDocument = {
  schema_version?: string;
  name?: string | null;
  nodes: BackendGraphNode[];
  edges: BackendGraphEdge[];
  metadata?: JsonObject;
};

export type GraphValidateRequest = {
  graph: BackendGraphDocument;
};

export type GraphValidateResponse = {
  valid: boolean;
  errors: Diagnostic[];
  warnings: Diagnostic[];
};

export type GraphCompileRequest = {
  graph: BackendGraphDocument;
  compile_options?: JsonObject;
};

export type GraphCompileResponse = {
  valid: boolean;
  build_config?: JsonObject | null;
  run_config?: JsonObject | null;
  publish_config?: JsonObject | null;
  rules_config?: JsonObject | null;
  graph_config?: JsonObject | null;
  diagnostics: Diagnostic[];
  warnings: Diagnostic[];
};

export type SecretRequirementStatus = 'missing' | 'partial' | 'satisfied';

export type SecretFieldRequirement = {
  name: string;
  title?: string | null;
  description?: string | null;
  secret: boolean;
  required: boolean;
  config_path?: string | null;
};

export type SecretUsage = {
  node_id: string;
  node_title?: string | null;
  node_type?: string | null;
  port_id?: string | null;
};

export type SecretRequirement = {
  secret_ref: string;
  kind: string;
  title: string;
  description?: string | null;
  fields: SecretFieldRequirement[];
  used_by: SecretUsage[];
  status: SecretRequirementStatus;
};

export type SecretRequirementsRequest = {
  graph?: BackendGraphDocument | null;
  build_config?: JsonObject | null;
};

export type SecretRequirementsResponse = {
  requirements: SecretRequirement[];
};

export type StoreSessionSecretRequest = {
  secret_ref: string;
  kind: string;
  scope?: 'session';
  ttl_seconds?: number | null;
  values: Record<string, string>;
};

export type SecretFieldStatus = {
  name: string;
  secret: boolean;
  has_value: boolean;
};

export type SessionSecretStatus = {
  secret_ref: string;
  kind: string;
  scope: 'session';
  fields: SecretFieldStatus[];
  created_at: string;
  expires_at?: string | null;
};

export type SessionSecretListResponse = {
  items: SessionSecretStatus[];
};

export type StoreSessionSecretResponse = {
  secret_ref: string;
  status: 'stored';
  item: SessionSecretStatus;
};

export type DeleteSessionSecretResponse = {
  secret_ref: string;
  status: 'deleted' | 'not_found';
};

export type ClearSessionSecretsResponse = {
  status: 'cleared';
  deleted_count: number;
};

export type RunStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelling' | 'cancelled';

export type RunCreateRequest = {
  valid?: boolean | null;
  build_config: JsonObject;
  run_config?: JsonObject | null;
  publish_config?: JsonObject | null;
  rules_config?: JsonObject | null;
  graph_config?: JsonObject | null;
  diagnostics?: JsonValue[];
  warnings?: JsonValue[];
  run_options?: JsonObject;
};

export type RunCreateResponse = {
  run_id: string;
  status: RunStatus;
};

export type RunSummary = {
  id: string;
  name?: string | null;
  status: RunStatus;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type RunDetails = RunSummary & {
  progress: JsonObject;
  build_config: JsonObject;
  run_config?: JsonObject | null;
  publish_config?: JsonObject | null;
  rules_config?: JsonObject | null;
  graph_config?: JsonObject | null;
  error?: string | null;
};

export type RunListResponse = {
  items: RunSummary[];
};

export type LogItem = {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
};

export type RunLogsResponse = {
  items: LogItem[];
};

export type RunEvent = {
  id: number;
  type: string;
  timestamp?: string;
  data: JsonObject;
};

export type ArtifactSummary = {
  id: string;
  name: string;
  kind: 'file' | 'directory';
  mime_type: string;
  size: number;
};

export type ArtifactListResponse = {
  items: ArtifactSummary[];
};

export type ArtifactPreview = {
  artifact_id: string;
  kind: 'text' | 'json' | 'unsupported';
  content?: string | JsonObject | JsonValue[] | null;
  message?: string | null;
};

export type PluginCapability = {
  namespace: string;
  id: string;
};

export type PluginStatus = 'active' | 'disabled' | 'pending_restart' | 'error';

export type PluginInfo = {
  id: string;
  version?: string | null;
  name?: string | null;
  enabled: boolean;
  loaded: boolean;
  status: PluginStatus;
  restart_required: boolean;
  capabilities: PluginCapability[];
  metadata: JsonObject;
};

export type PluginListResponse = {
  items: PluginInfo[];
};

export type PluginPatchRequest = {
  enabled: boolean;
};

export type PluginRuntimeDiagnostic = {
  plugin_id?: string | null;
  phase: string;
  code: string;
  message: string;
  details: JsonObject;
};

export type PluginRuntimeStatusResponse = {
  active: boolean;
  plugin_ids: string[];
  capabilities: PluginCapability[];
  diagnostics: PluginRuntimeDiagnostic[];
  error?: string | null;
};

export type ProjectCreateRequest = {
  name: string;
  description?: string | null;
  graph: BackendGraphDocument;
};

export type ProjectUpdateRequest = {
  name?: string | null;
  description?: string | null;
  graph?: BackendGraphDocument | null;
};

export type Project = {
  id: string;
  name: string;
  description?: string | null;
  graph: BackendGraphDocument;
  created_at: string;
  updated_at: string;
};

export type ProjectListResponse = {
  items: Project[];
};
