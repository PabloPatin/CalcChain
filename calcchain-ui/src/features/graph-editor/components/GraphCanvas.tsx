import type {
  DragEvent,
  MouseEvent as ReactMouseEvent,
  RefObject,
} from "react";
import { useMemo, useState } from "react";
import { Network } from "lucide-react";

import type {
  BlockDescriptor,
  CanvasPosition,
  ConnectionCheckResult,
  EdgeId,
  GraphEdge,
  GraphNode as GraphNodeModel,
  GraphPortEndpoint,
  NodeId,
  PortDirection,
} from "../model/types";

import { GraphNode } from "./GraphNode";
import { EdgeLayer } from "./EdgeLayer";

export interface PendingConnectionLike {
  from: GraphPortEndpoint;
}

export interface GraphCanvasProps {
  canvasRef: RefObject<HTMLDivElement | null>;
  
  descriptors: BlockDescriptor[];

  nodes: GraphNodeModel[];
  edges: GraphEdge[];

  selectedNodeId: NodeId | null;
  selectedEdgeId: EdgeId | null;

  pendingConnection: PendingConnectionLike | null;
  isCompatibleInput: (nodeId: NodeId, portId: string) => boolean;

  portPositions: Record<string, CanvasPosition>;
  registerPort: (
    nodeId: NodeId,
    direction: PortDirection,
    portId: string,
    element: HTMLElement | null,
  ) => void;

  onSelectNode: (nodeId: NodeId | null) => void;
  onSelectEdge: (edgeId: EdgeId | null) => void;

  onAddNode: (
    descriptor: BlockDescriptor,
    position: CanvasPosition,
  ) => GraphNodeModel;

  onMoveNode: (nodeId: NodeId, position: CanvasPosition) => void;

  onStartConnection: (from: GraphPortEndpoint) => void;
  onCompleteConnection: (to: GraphPortEndpoint) => ConnectionCheckResult;

  onMessage?: (message: string) => void;
}

interface NodeDragState {
  nodeId: NodeId;
  startPointer: CanvasPosition;
  startPosition: CanvasPosition;
}

function getDescriptorByType(
  descriptors: BlockDescriptor[],
  type: string,
): BlockDescriptor | undefined {
  return descriptors.find((descriptor) => descriptor.type === type);
}

function getPreferredNodeSize(descriptor: BlockDescriptor) {
  return {
    width: descriptor.defaultSize?.width ?? 252,
    height: descriptor.defaultSize?.height ?? 168,
  };
}

function getCanvasPoint(
  canvasRef: RefObject<HTMLDivElement | null>,
  clientX: number,
  clientY: number,
): CanvasPosition {
  const rect = canvasRef.current?.getBoundingClientRect();

  if (!rect) {
    return {
      x: clientX,
      y: clientY,
    };
  }

  return {
    x: clientX - rect.left,
    y: clientY - rect.top,
  };
}

export function GraphCanvas({
  canvasRef,
  descriptors,
  nodes,
  edges,
  selectedNodeId,
  selectedEdgeId,
  pendingConnection,
  isCompatibleInput,
  portPositions,
  registerPort,
  onSelectNode,
  onSelectEdge,
  onAddNode,
  onMoveNode,
  onStartConnection,
  onCompleteConnection,
  onMessage,
}: GraphCanvasProps) {
  const [dragState, setDragState] = useState<NodeDragState | null>(null);

  const descriptorByType = useMemo(
    () => new Map(descriptors.map((descriptor) => [descriptor.type, descriptor])),
    [descriptors],
  );

  function addDescriptorAtPoint(
    descriptor: BlockDescriptor,
    point: CanvasPosition,
  ) {
    const size = getPreferredNodeSize(descriptor);

    onAddNode(descriptor, {
      x: Math.max(16, point.x - size.width / 2),
      y: Math.max(16, point.y - size.height / 2),
    });
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();

    const blockType =
      event.dataTransfer.getData("application/x-calcchain-block") ||
      event.dataTransfer.getData("text/plain");

    const descriptor = getDescriptorByType(descriptors, blockType);

    if (!descriptor) {
      onMessage?.(`Unknown block type: ${blockType}`);
      return;
    }

    addDescriptorAtPoint(
      descriptor,
      getCanvasPoint(canvasRef, event.clientX, event.clientY),
    );
  }

  function handleNodePointerDown(
    event: ReactMouseEvent<HTMLDivElement>,
    nodeId: NodeId,
  ) {
    event.stopPropagation();

    const node = nodes.find((candidate) => candidate.id === nodeId);

    if (!node) {
      return;
    }

    setDragState({
      nodeId,
      startPointer: {
        x: event.clientX,
        y: event.clientY,
      },
      startPosition: node.position,
    });

    onSelectNode(nodeId);
  }

  function handleMouseMove(event: ReactMouseEvent<HTMLDivElement>) {
    if (!dragState) {
      return;
    }

    const dx = event.clientX - dragState.startPointer.x;
    const dy = event.clientY - dragState.startPointer.y;

    onMoveNode(dragState.nodeId, {
      x: Math.max(16, dragState.startPosition.x + dx),
      y: Math.max(16, dragState.startPosition.y + dy),
    });
  }

  function handleMouseUp() {
    setDragState(null);
  }

  function handlePortClick(
    endpoint: GraphPortEndpoint,
    direction: PortDirection,
  ) {
    if (direction === "output") {
      onStartConnection(endpoint);
      onMessage?.("Выбран выходной порт. Теперь выбери совместимый вход.");
      return;
    }

    const result = onCompleteConnection(endpoint);

    if (!result.ok) {
      onMessage?.(result.reason);
      return;
    }

    onMessage?.("Соединение создано.");
  }

  return (
    <div
      className="relative min-h-0 flex-1 overflow-auto"
      onClick={() => {
        onSelectNode(null);
        onSelectEdge(null);
      }}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <div
        ref={canvasRef}
        className="relative h-[860px] w-[1800px]"
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(15, 23, 42, 0.06) 1px, transparent 1px), linear-gradient(to bottom, rgba(15, 23, 42, 0.06) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      >
        {nodes.length === 0 && (
          <div className="absolute left-1/2 top-1/2 w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-3xl border border-dashed border-slate-300 bg-white/70 p-8 text-center shadow-sm backdrop-blur">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-3xl bg-slate-100 text-slate-500">
              <Network size={26} />
            </div>

            <h2 className="mt-4 text-lg font-semibold text-slate-950">
              Рабочая область пуста
            </h2>

            <p className="mt-2 text-sm leading-6 text-slate-500">
              Перетащи блок из палитры слева или дважды кликни по нему.
              Затем выбери выходной порт и подключи его к совместимому входному
              порту.
            </p>
          </div>
        )}

        <EdgeLayer
          edges={edges}
          nodes={nodes}
          descriptors={descriptors}
          portPositions={portPositions}
          selectedEdgeId={selectedEdgeId}
          onSelectEdge={onSelectEdge}
        />

        {nodes.map((node) => {
          const descriptor = descriptorByType.get(node.type);

          if (!descriptor) {
            return null;
          }

          return (
            <GraphNode
              key={node.id}
              node={node}
              descriptor={descriptor}
              selected={selectedNodeId === node.id}
              pendingConnectionFrom={pendingConnection?.from ?? null}
              isCompatibleInput={isCompatibleInput}
              onSelect={onSelectNode}
              onPointerDown={handleNodePointerDown}
              onPortClick={handlePortClick}
              registerPort={registerPort}
            />
          );
        })}
      </div>
    </div>
  );
}