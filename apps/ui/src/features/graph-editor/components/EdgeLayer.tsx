import type {
  BlockDescriptor,
  EdgeId,
  GraphEdge,
  GraphNode,
  PortDirection,
  PortId,
  PortPositionMap,
} from "../model/types";

import { createEdgePath } from "../utils/edgeGeometry";
import { createPortPositionKey } from "../hooks/usePortPositions";

export interface EdgeLayerProps {
  edges: GraphEdge[];
  nodes: GraphNode[];
  descriptors: BlockDescriptor[];
  portPositions: PortPositionMap;

  selectedEdgeId: EdgeId | null;
  onSelectEdge: (edgeId: EdgeId) => void;
}

function getDescriptor(
  descriptors: BlockDescriptor[],
  node: GraphNode,
): BlockDescriptor | undefined {
  return descriptors.find((descriptor) => descriptor.type === node.type);
}

function getFallbackNodeSize(descriptor: BlockDescriptor) {
  const portRows = Math.max(
    descriptor.inputs.length,
    descriptor.outputs.length,
    1,
  );

  return {
    width: descriptor.defaultSize?.width ?? 252,
    height: Math.max(
      descriptor.defaultSize?.height ?? 168,
      112 + portRows * 34,
    ),
  };
}

function getFallbackPortPosition(
  node: GraphNode,
  descriptor: BlockDescriptor,
  direction: PortDirection,
  portId: PortId,
) {
  const ports = direction === "input" ? descriptor.inputs : descriptor.outputs;
  const index = Math.max(
    0,
    ports.findIndex((port) => port.id === portId),
  );

  const size = getFallbackNodeSize(descriptor);

  return {
    x:
      direction === "output"
        ? node.position.x + size.width
        : node.position.x,
    y: node.position.y + 106 + index * 34,
  };
}

export function EdgeLayer({
  edges,
  nodes,
  descriptors,
  portPositions,
  selectedEdgeId,
  onSelectEdge,
}: EdgeLayerProps) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  return (
    <svg className="pointer-events-none absolute inset-0 z-30 h-full w-full overflow-visible">
        <defs>
            <marker
            id="edge-arrow-default"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
            >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
            </marker>

            <marker
            id="edge-arrow-selected"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
            >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#0f172a" />
            </marker>
        </defs>

      {edges.map((edge) => {
        const fromNode = nodeById.get(edge.source.node_id);
        const toNode = nodeById.get(edge.target.node_id);

        if (!fromNode || !toNode) {
          return null;
        }

        const fromDescriptor = getDescriptor(descriptors, fromNode);
        const toDescriptor = getDescriptor(descriptors, toNode);

        if (!fromDescriptor || !toDescriptor) {
          return null;
        }

        const start =
          portPositions[
            createPortPositionKey(
              edge.source.node_id,
              "output",
              edge.source.port_id,
            )
          ] ??
          getFallbackPortPosition(
            fromNode,
            fromDescriptor,
            "output",
            edge.source.port_id,
          );

        const end =
          portPositions[
            createPortPositionKey(edge.target.node_id, "input", edge.target.port_id)
          ] ??
          getFallbackPortPosition(
            toNode,
            toDescriptor,
            "input",
            edge.target.port_id,
          );

        const selected = selectedEdgeId === edge.id;

        return (
          <g key={edge.id}>
            <path
              d={createEdgePath(start, end)}
              fill="none"
              strokeWidth="12"
              stroke="transparent"
              className="cursor-pointer"
              style={{ pointerEvents: "stroke" }}
              onClick={(event) => {
                event.stopPropagation();
                onSelectEdge(edge.id);
              }}
            />

            <path
              d={createEdgePath(start, end)}
              fill="none"
              strokeWidth={selected ? 3 : 2.25}
              className={selected ? "stroke-slate-950" : "stroke-slate-500"}
              style={{ pointerEvents: "none" }}
              markerEnd={selected ? "url(#edge-arrow-selected)" : "url(#edge-arrow-default)"}
            />
          </g>
        );
      })}
    </svg>
  );
}
