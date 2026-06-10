import { useState } from "react";
import { Eye, EyeOff, Trash2, X } from "lucide-react";

import type { JsonObject, JsonValue } from "../../../shared/api/backendTypes";
import type {
  BlockData,
  BlockDescriptor,
  EdgeId,
  GraphEdge,
  GraphNode,
  NodeId,
} from "../model/types";

const INTERNAL_CONFIG_FIELDS = new Set(["credential_ref", "secret_ref"]);

interface ConfigField {
  key: string;
  value: JsonValue;
  title: string;
  secret: boolean;
  multiline: boolean;
  enumValues: string[];
}

export interface InspectorProps {
  selectedNode: GraphNode | null;
  selectedEdge: GraphEdge | null;
  validationDebug: unknown | null;

  nodes: GraphNode[];
  edges: GraphEdge[];
  descriptors: BlockDescriptor[];

  onUpdateNodeData: (nodeId: NodeId, dataPatch: Partial<BlockData>) => void;
  onDeleteNode: (nodeId: NodeId) => void;
  onDeleteEdge: (edgeId: EdgeId) => void;
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  return JSON.stringify(value, null, 2);
}

function parseValueLikeOriginal(original: JsonValue, raw: string): JsonValue {
  if (typeof original === "number") {
    const parsed = Number(raw);
    return Number.isNaN(parsed) ? original : parsed;
  }

  if (typeof original === "boolean") {
    return raw === "true";
  }

  if (Array.isArray(original) || typeof original === "object") {
    try {
      return normalizeJsonValue(JSON.parse(raw));
    } catch {
      return original;
    }
  }

  return raw;
}

function normalizeJsonValue(value: unknown): JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }

  if (Array.isArray(value)) {
    return value.map(normalizeJsonValue);
  }

  if (typeof value === "object") {
    const result: Record<string, JsonValue> = {};
    for (const [key, child] of Object.entries(value)) {
      result[key] = normalizeJsonValue(child);
    }
    return result;
  }

  return String(value);
}

function getConfigFields(
  selectedNode: GraphNode,
  descriptors: BlockDescriptor[],
): ConfigField[] {
  const descriptor = descriptors.find((item) => item.type === selectedNode.type);
  const properties = getSchemaProperties(descriptor?.configSchema);
  const fieldKeys = new Set<string>();
  const fields: ConfigField[] = [];

  if (properties) {
    for (const [key, rawSchema] of Object.entries(properties)) {
      if (!isJsonObject(rawSchema)) {
        continue;
      }
      fieldKeys.add(key);
      fields.push({
        key,
        value: Object.prototype.hasOwnProperty.call(selectedNode.config, key)
          ? selectedNode.config[key]
          : defaultValueForSchema(rawSchema),
        title: typeof rawSchema.title === "string" ? rawSchema.title : key,
        secret: isSecretProperty(rawSchema),
        multiline: isMultilineProperty(key, rawSchema),
        enumValues: enumValuesForSchema(rawSchema),
      });
    }
  }

  for (const [key, value] of Object.entries(selectedNode.config)) {
    if (fieldKeys.has(key) || INTERNAL_CONFIG_FIELDS.has(key)) {
      continue;
    }
    fields.push({
      key,
      value,
      title: key,
      secret: false,
      multiline: false,
      enumValues: [],
    });
  }

  return fields;
}

function defaultValueForSchema(schema: JsonObject): JsonValue {
  return Object.prototype.hasOwnProperty.call(schema, "default") ? schema.default : "";
}

function enumValuesForSchema(schema: JsonObject): string[] {
  const enumValue = schema.enum;
  if (!Array.isArray(enumValue)) {
    return [];
  }

  return enumValue
    .filter(
      (value) =>
        typeof value === "string" ||
        typeof value === "number" ||
        typeof value === "boolean",
    )
    .map(String);
}

function getSchemaProperties(schema: unknown): JsonObject | null {
  if (!isJsonObject(schema)) {
    return null;
  }
  return isJsonObject(schema.properties) ? schema.properties : null;
}

function isSecretProperty(value: JsonObject): boolean {
  return (
    value["x-calcchain-credential"] === "secret" ||
    value["x-calcchain-secret"] === true ||
    value["x-secret"] === true ||
    value.secret === true ||
    value.format === "password" ||
    value.writeOnly === true
  );
}

function isMultilineProperty(key: string, value: JsonObject): boolean {
  return key === "stdin_text" || value.format === "textarea" || value["x-calcchain-multiline"] === true;
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getNodeTitle(nodes: GraphNode[], nodeId: NodeId): string {
  return nodes.find((node) => node.id === nodeId)?.title ?? "unknown";
}

function ValidationDebugPanel({ value }: { value: unknown | null }) {
  if (value === null) {
    return null;
  }

  return (
    <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 p-4">
      <div className="text-sm font-semibold text-rose-950">
        Validation debug
      </div>
      <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-white p-3 font-mono text-[11px] leading-4 text-rose-950">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export function Inspector({
  selectedNode,
  selectedEdge,
  validationDebug,
  nodes,
  edges,
  descriptors,
  onUpdateNodeData,
  onDeleteNode,
  onDeleteEdge,
}: InspectorProps) {
  const [visibleSecrets, setVisibleSecrets] = useState<Set<string>>(new Set());

  function isSecretVisible(nodeId: string, fieldName: string): boolean {
    return visibleSecrets.has(`${nodeId}:${fieldName}`);
  }

  function toggleSecretVisibility(nodeId: string, fieldName: string) {
    setVisibleSecrets((current) => {
      const key = `${nodeId}:${fieldName}`;
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  if (selectedEdge) {
    return (
      <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white/90 p-5 xl:block">
        <ValidationDebugPanel value={validationDebug} />

        <div className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Selected connection
        </div>

        <h2 className="mt-1 text-xl font-semibold text-slate-950">
          Connection
        </h2>

        <div className="mt-6 rounded-3xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          <div>
            <span className="text-slate-400">from</span>{" "}
            {getNodeTitle(nodes, selectedEdge.source.node_id)}.
            {selectedEdge.source.port_id}
          </div>

          <div className="mt-2">
            <span className="text-slate-400">to</span>{" "}
            {getNodeTitle(nodes, selectedEdge.target.node_id)}.{selectedEdge.target.port_id}
          </div>
        </div>

        <button
          type="button"
          onClick={() => onDeleteEdge(selectedEdge.id)}
          className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
        >
          <Trash2 size={16} />
          Delete connection
        </button>
      </aside>
    );
  }

  if (!selectedNode) {
    return (
      <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white/90 p-5 xl:block">
        <ValidationDebugPanel value={validationDebug} />

        <div className="rounded-3xl border border-dashed border-slate-300 p-5 text-sm leading-6 text-slate-500">
          Выбери блок или соединение, чтобы посмотреть параметры.
        </div>
      </aside>
    );
  }

  const nodeEdges = edges.filter(
    (edge) =>
      edge.source.node_id === selectedNode.id ||
      edge.target.node_id === selectedNode.id,
  );
  const configFields = getConfigFields(selectedNode, descriptors);

  return (
    <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white/90 p-5 xl:block">
      <ValidationDebugPanel value={validationDebug} />

      <div className="text-sm font-semibold uppercase tracking-wide text-slate-400">
        Selected block
      </div>

      <h2 className="mt-1 text-xl font-semibold text-slate-950">
        {selectedNode.title}
      </h2>

      <div className="mt-6 rounded-3xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-900">Block data</div>

        <div className="mt-3 space-y-3">
          {configFields.map(({ key, value, title, secret, multiline, enumValues }) => {
            const isComplex = typeof value === "object" && value !== null;

            return (
              <label key={key} className="block">
                <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  {title}
                </span>

                {enumValues.length > 0 ? (
                  <select
                    value={stringifyValue(value)}
                    onChange={(event) =>
                      onUpdateNodeData(selectedNode.id, {
                        [key]: parseValueLikeOriginal(value, event.target.value),
                      })
                    }
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-slate-400"
                  >
                    {enumValues.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                ) : isComplex || multiline ? (
                  <textarea
                    value={stringifyValue(value)}
                    onChange={(event) =>
                      onUpdateNodeData(selectedNode.id, {
                        [key]: parseValueLikeOriginal(value, event.target.value),
                      })
                    }
                    className="mt-1 min-h-24 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-700 outline-none"
                  />
                ) : (
                  <div className="mt-1 flex rounded-xl border border-slate-200 bg-white focus-within:border-slate-400">
                    <input
                      type={secret && !isSecretVisible(selectedNode.id, key) ? "password" : "text"}
                      value={stringifyValue(value)}
                      onChange={(event) =>
                        onUpdateNodeData(selectedNode.id, {
                          [key]: parseValueLikeOriginal(value, event.target.value),
                        })
                      }
                      className="min-w-0 flex-1 rounded-xl bg-transparent px-3 py-2 text-sm text-slate-700 outline-none"
                    />
                    {secret && (
                      <button
                        type="button"
                        aria-label={isSecretVisible(selectedNode.id, key) ? "Hide secret" : "Show secret"}
                        title={isSecretVisible(selectedNode.id, key) ? "Hide secret" : "Show secret"}
                        onClick={() => toggleSecretVisibility(selectedNode.id, key)}
                        className="grid w-10 place-items-center rounded-xl text-slate-400 hover:bg-slate-50 hover:text-slate-700"
                      >
                        {isSecretVisible(selectedNode.id, key) ? (
                          <EyeOff size={16} />
                        ) : (
                          <Eye size={16} />
                        )}
                      </button>
                    )}
                  </div>
                )}
              </label>
            );
          })}
        </div>
      </div>

      <div className="mt-4 rounded-3xl border border-slate-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-900">Connections</div>

        {nodeEdges.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">Нет подключений.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {nodeEdges.map((edge) => {
              const outgoing = edge.source.node_id === selectedNode.id;
              const label = outgoing
                ? `${edge.source.port_id} -> ${getNodeTitle(nodes, edge.target.node_id)}.${edge.target.port_id}`
                : `${getNodeTitle(nodes, edge.source.node_id)}.${edge.source.port_id} -> ${edge.target.port_id}`;

              return (
                <div
                  key={edge.id}
                  className="flex items-center justify-between gap-2 rounded-2xl bg-slate-50 px-3 py-2 text-xs text-slate-600"
                >
                  <span className="truncate">{label}</span>

                  <button
                    type="button"
                    onClick={() => onDeleteEdge(edge.id)}
                    className="rounded-lg p-1 text-slate-400 hover:bg-white hover:text-slate-700"
                  >
                    <X size={14} />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => onDeleteNode(selectedNode.id)}
        className="mt-4 flex w-full items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
      >
        <Trash2 size={16} />
        Delete block
      </button>
    </aside>
  );
}
