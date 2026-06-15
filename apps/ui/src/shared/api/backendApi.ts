import {
  apiFetch,
  apiFetchBlob,
  apiFetchRaw,
  createApiHeaders,
  getApiUrl,
} from './apiClient';
import type {
  ArtifactListResponse,
  ArtifactPreview,
  AuthState,
  BackendGraphDocument,
  CatalogResponse,
  ClearSessionSecretsResponse,
  ConnectionRule,
  DeleteSessionSecretResponse,
  GraphCompileResponse,
  GraphManifestImportResponse,
  GraphValidateResponse,
  HealthResponse,
  JsonObject,
  PairingResponse,
  PluginInfo,
  PluginListResponse,
  PluginPatchRequest,
  PluginRuntimeStatusResponse,
  Project,
  ProjectCreateRequest,
  ProjectListResponse,
  ProjectUpdateRequest,
  RunCreateRequest,
  RunCreateResponse,
  RunDetails,
  RunEvent,
  RunListResponse,
  RunLogsResponse,
  SecretRequirementsRequest,
  SecretRequirementsResponse,
  ServerInfo,
  SessionSecretListResponse,
  StoreSessionSecretRequest,
  StoreSessionSecretResponse,
} from './backendTypes';

export function getServerInfo(): Promise<ServerInfo> {
  return apiFetch<ServerInfo>('/api/server/info');
}

export function getServerHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/api/server/health');
}

export function getAuthState(): Promise<AuthState> {
  return apiFetch<AuthState>('/api/auth/state');
}

export function pairWithCode(code: string): Promise<PairingResponse> {
  return apiFetch<PairingResponse>('/api/auth/pair', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
}

export function logoutSession(): Promise<void> {
  return apiFetch<void>('/api/auth/logout', { method: 'POST' });
}

export function getCatalog(): Promise<CatalogResponse> {
  return apiFetch<CatalogResponse>('/api/catalog');
}

export function getConnectionRules(): Promise<ConnectionRule[]> {
  return apiFetch<ConnectionRule[]>('/api/catalog/connection-rules');
}

export function validateGraph(graph: BackendGraphDocument): Promise<GraphValidateResponse> {
  return apiFetch<GraphValidateResponse>('/api/graphs/validate', {
    method: 'POST',
    body: JSON.stringify({ graph }),
  });
}

export function compileGraph(
  graph: BackendGraphDocument,
  compileOptions: JsonObject = {},
): Promise<GraphCompileResponse> {
  return apiFetch<GraphCompileResponse>('/api/graphs/compile', {
    method: 'POST',
    body: JSON.stringify({ graph, compile_options: compileOptions }),
  });
}

export async function importManifest(file: File): Promise<GraphManifestImportResponse> {
  return apiFetch<GraphManifestImportResponse>('/api/graphs/import/manifest', {
    method: 'POST',
    body: await file.text(),
  });
}

export function getSecretRequirements(
  request: SecretRequirementsRequest,
): Promise<SecretRequirementsResponse> {
  return apiFetch<SecretRequirementsResponse>('/api/secrets/requirements', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function listSessionSecrets(): Promise<SessionSecretListResponse> {
  return apiFetch<SessionSecretListResponse>('/api/secrets/session');
}

export function storeSessionSecret(
  request: StoreSessionSecretRequest,
): Promise<StoreSessionSecretResponse> {
  return apiFetch<StoreSessionSecretResponse>('/api/secrets/session', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function deleteSessionSecret(secretRef: string): Promise<DeleteSessionSecretResponse> {
  return apiFetch<DeleteSessionSecretResponse>(`/api/secrets/session/${encodePathSegment(secretRef)}`, {
    method: 'DELETE',
  });
}

export function clearSessionSecrets(): Promise<ClearSessionSecretsResponse> {
  return apiFetch<ClearSessionSecretsResponse>('/api/secrets/session/clear', {
    method: 'POST',
  });
}

export function createRun(request: RunCreateRequest | GraphCompileResponse): Promise<RunCreateResponse> {
  return apiFetch<RunCreateResponse>('/api/runs', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function listRuns(): Promise<RunListResponse> {
  return apiFetch<RunListResponse>('/api/runs');
}

export function getRun(runId: string): Promise<RunDetails> {
  return apiFetch<RunDetails>(`/api/runs/${encodePathSegment(runId)}`);
}

export function cancelRun(runId: string): Promise<RunDetails> {
  return apiFetch<RunDetails>(`/api/runs/${encodePathSegment(runId)}/cancel`, {
    method: 'POST',
  });
}

export function getRunLogs(runId: string): Promise<RunLogsResponse> {
  return apiFetch<RunLogsResponse>(`/api/runs/${encodePathSegment(runId)}/logs`);
}

export function listRunArtifacts(runId: string): Promise<ArtifactListResponse> {
  return apiFetch<ArtifactListResponse>(`/api/runs/${encodePathSegment(runId)}/artifacts`);
}

export function previewRunArtifact(runId: string, artifactId: string): Promise<ArtifactPreview> {
  return apiFetch<ArtifactPreview>(
    `/api/runs/${encodePathSegment(runId)}/artifacts/${encodePathSegment(artifactId)}/preview`,
  );
}

export function downloadRunArtifact(runId: string, artifactId: string): Promise<Blob> {
  return apiFetchBlob(
    `/api/runs/${encodePathSegment(runId)}/artifacts/${encodePathSegment(artifactId)}`,
  );
}

export function getRunArtifactUrl(runId: string, artifactId: string): string {
  return getApiUrl(`/api/runs/${encodePathSegment(runId)}/artifacts/${encodePathSegment(artifactId)}`);
}

export async function streamRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  options: { signal?: AbortSignal } = {},
): Promise<void> {
  const response = await apiFetchRaw(`/api/runs/${encodePathSegment(runId)}/events`, {
    signal: options.signal,
    headers: createApiHeaders(),
  });
  const stream = response.body;
  if (stream === null) {
    return;
  }

  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const chunk = await reader.read();
    if (chunk.done) {
      break;
    }
    buffer += decoder.decode(chunk.value, { stream: true });
    buffer = consumeSseBuffer(buffer, onEvent);
  }

  buffer += decoder.decode();
  consumeSseBuffer(`${buffer}\n\n`, onEvent);
}

export function listPlugins(): Promise<PluginListResponse> {
  return apiFetch<PluginListResponse>('/api/plugins');
}

export function patchPlugin(pluginId: string, request: PluginPatchRequest): Promise<PluginInfo> {
  return apiFetch<PluginInfo>(`/api/plugins/${encodePathSegment(pluginId)}`, {
    method: 'PATCH',
    body: JSON.stringify(request),
  });
}

export function getPluginRuntimeStatus(): Promise<PluginRuntimeStatusResponse> {
  return apiFetch<PluginRuntimeStatusResponse>('/api/plugins/runtime/status');
}

export function reloadPluginRuntime(): Promise<PluginRuntimeStatusResponse> {
  return apiFetch<PluginRuntimeStatusResponse>('/api/plugins/runtime/reload', {
    method: 'POST',
  });
}

export function listProjects(): Promise<ProjectListResponse> {
  return apiFetch<ProjectListResponse>('/api/projects');
}

export function createProject(request: ProjectCreateRequest): Promise<Project> {
  return apiFetch<Project>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

export function getProject(projectId: string): Promise<Project> {
  return apiFetch<Project>(`/api/projects/${encodePathSegment(projectId)}`);
}

export function updateProject(projectId: string, request: ProjectUpdateRequest): Promise<Project> {
  return apiFetch<Project>(`/api/projects/${encodePathSegment(projectId)}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  });
}

export function deleteProject(projectId: string): Promise<void> {
  return apiFetch<void>(`/api/projects/${encodePathSegment(projectId)}`, {
    method: 'DELETE',
  });
}

function consumeSseBuffer(buffer: string, onEvent: (event: RunEvent) => void): string {
  const frames = buffer.split(/\r?\n\r?\n/);
  const tail = frames.pop() ?? '';

  for (const frame of frames) {
    const event = parseRunEventFrame(frame);
    if (event !== null) {
      onEvent(event);
    }
  }

  return tail;
}

function parseRunEventFrame(frame: string): RunEvent | null {
  const lines = frame.split(/\r?\n/);
  let id = 0;
  let type = 'message';
  const dataLines: string[] = [];

  for (const line of lines) {
    if (line.startsWith('id:')) {
      id = Number.parseInt(line.slice(3).trim(), 10);
    } else if (line.startsWith('event:')) {
      type = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  if (dataLines.length === 0) {
    return null;
  }

  const data = parseEventData(dataLines.join('\n'));
  return {
    id: Number.isFinite(id) ? id : 0,
    type,
    data,
  };
}

function parseEventData(rawData: string): JsonObject {
  try {
    const parsed: unknown = JSON.parse(rawData);
    if (isJsonObject(parsed)) {
      return parsed;
    }
  } catch {
    return { message: rawData };
  }
  return { value: rawData };
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function encodePathSegment(value: string): string {
  return encodeURIComponent(value);
}
