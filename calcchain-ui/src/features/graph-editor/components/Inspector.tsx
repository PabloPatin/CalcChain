import { Trash2, X } from "lucide-react";

import type {
  BlockData,
  BlockDescriptor,
  EdgeId,
  GraphEdge,
  GraphNode,
  NodeId,
} from "../model/types";

export interface InspectorProps {
  selectedNode: GraphNode | null;
  selectedEdge: GraphEdge | null;

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

function parseValueLikeOriginal(original: unknown, raw: string): unknown {
  if (typeof original === "number") {
    const parsed = Number(raw);
    return Number.isNaN(parsed) ? original : parsed;
  }

  if (typeof original === "boolean") {
    return raw === "true";
  }

  if (Array.isArray(original) || typeof original === "object") {
    try {
      return JSON.parse(raw);
    } catch {
      return original;
    }
  }

  return raw;
}

function getNodeTitle(nodes: GraphNode[], nodeId: NodeId): string {
  return nodes.find((node) => node.id === nodeId)?.title ?? "unknown";
}

export function Inspector({
  selectedNode,
  selectedEdge,
  nodes,
  edges,
  onUpdateNodeData,
  onDeleteNode,
  onDeleteEdge,
}: InspectorProps) {
  if (selectedEdge) {
    return (
      <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white/90 p-5 xl:block">
        <div className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Selected connection
        </div>

        <h2 className="mt-1 text-xl font-semibold text-slate-950">
          Connection
        </h2>

        <div className="mt-6 rounded-3xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          <div>
            <span className="text-slate-400">from</span>{" "}
            {getNodeTitle(nodes, selectedEdge.from.nodeId)}.
            {selectedEdge.from.portId}
          </div>

          <div className="mt-2">
            <span className="text-slate-400">to</span>{" "}
            {getNodeTitle(nodes, selectedEdge.to.nodeId)}.{selectedEdge.to.portId}
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
      <aside className="hidden w-80 shrink-0 border-l border-slate-200 bg-white/90 p-5 xl:block">
        <div className="rounded-3xl border border-dashed border-slate-300 p-5 text-sm leading-6 text-slate-500">
          Выбери блок или соединение, чтобы посмотреть параметры.
        </div>
      </aside>
    );
  }

  const nodeEdges = edges.filter(
    (edge) =>
      edge.from.nodeId === selectedNode.id ||
      edge.to.nodeId === selectedNode.id,
  );

  return (
    <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-slate-200 bg-white/90 p-5 xl:block">
      <div className="text-sm font-semibold uppercase tracking-wide text-slate-400">
        Selected block
      </div>

      <h2 className="mt-1 text-xl font-semibold text-slate-950">
        {selectedNode.title}
      </h2>

      <div className="mt-6 rounded-3xl border border-slate-200 bg-slate-50 p-4">
        <div className="text-sm font-semibold text-slate-900">Block data</div>

        <div className="mt-3 space-y-3">
          {Object.entries(selectedNode.data).map(([key, value]) => {
            const isComplex = typeof value === "object" && value !== null;

            return (
              <label key={key} className="block">
                <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                  {key}
                </span>

                {isComplex ? (
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
                  <input
                    value={stringifyValue(value)}
                    onChange={(event) =>
                      onUpdateNodeData(selectedNode.id, {
                        [key]: parseValueLikeOriginal(value, event.target.value),
                      })
                    }
                    className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none"
                  />
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
              const outgoing = edge.from.nodeId === selectedNode.id;
              const label = outgoing
                ? `${edge.from.portId} → ${getNodeTitle(nodes, edge.to.nodeId)}.${edge.to.portId}`
                : `${getNodeTitle(nodes, edge.from.nodeId)}.${edge.from.portId} → ${edge.to.portId}`;

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