import type {
  DragEvent,
  MouseEvent as ReactMouseEvent,
  RefObject,
} from "react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Network } from "lucide-react";

import type {
  BlockDescriptor,
  CanvasPosition,
  CanvasSize,
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

const MIN_CANVAS_WIDTH = 3600;
const MIN_CANVAS_HEIGHT = 1720;
const CANVAS_GROW_MARGIN = 720;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 2.25;
const ZOOM_FACTOR = 1.12;

export interface PendingConnectionLike {
  from: GraphPortEndpoint;
}

export interface GraphCanvasProps {
  canvasRef: RefObject<HTMLDivElement | null>;

  descriptors: BlockDescriptor[];

  nodes: GraphNodeModel[];
  edges: GraphEdge[];

  selectedNodeIds: Set<NodeId>;
  selectedEdgeId: EdgeId | null;
  invalidNodeIds: Set<NodeId>;

  pendingConnection: PendingConnectionLike | null;
  isCompatibleInput: (nodeId: NodeId, portId: string) => boolean;
  zoom: number;

  portPositions: Record<string, CanvasPosition>;
  registerPort: (
    nodeId: NodeId,
    direction: PortDirection,
    portId: string,
    element: HTMLElement | null,
  ) => void;

  onSelectNode: (nodeId: NodeId | null) => void;
  onSelectNodes: (nodeIds: NodeId[]) => void;
  onToggleNodeSelection: (nodeId: NodeId) => void;
  onSelectEdge: (edgeId: EdgeId | null) => void;

  onAddNode: (
    descriptor: BlockDescriptor,
    position: CanvasPosition,
  ) => GraphNodeModel;

  onMoveNodes: (positions: Record<NodeId, CanvasPosition>) => void;

  onStartConnection: (from: GraphPortEndpoint) => void;
  onCompleteConnection: (to: GraphPortEndpoint) => ConnectionCheckResult;
  onZoomChange: (zoom: number) => void;

  onMessage?: (message: string) => void;
}

interface NodeDragState {
  nodeIds: NodeId[];
  startPointer: CanvasPosition;
  startPositions: Record<NodeId, CanvasPosition>;
}

interface CanvasPanState {
  startPointer: CanvasPosition;
  startScrollLeft: number;
  startScrollTop: number;
}

interface ZoomAnchor {
  viewport: HTMLDivElement;
  pointerX: number;
  pointerY: number;
  worldX: number;
  worldY: number;
}

interface SelectionState {
  start: CanvasPosition;
  end: CanvasPosition;
}

interface SelectionRect {
  left: number;
  top: number;
  width: number;
  height: number;
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

function getCanvasSize(
  nodes: GraphNodeModel[],
  descriptorByType: Map<string, BlockDescriptor>,
): CanvasSize {
  let width = MIN_CANVAS_WIDTH;
  let height = MIN_CANVAS_HEIGHT;

  for (const node of nodes) {
    const descriptor = descriptorByType.get(node.type);
    const nodeSize = descriptor
      ? getPreferredNodeSize(descriptor)
      : { width: 252, height: 168 };

    width = Math.max(width, node.position.x + nodeSize.width + CANVAS_GROW_MARGIN);
    height = Math.max(height, node.position.y + nodeSize.height + CANVAS_GROW_MARGIN);
  }

  return { width, height };
}

function getCanvasPoint(
  canvasRef: RefObject<HTMLDivElement | null>,
  clientX: number,
  clientY: number,
  zoom: number,
): CanvasPosition {
  const rect = canvasRef.current?.getBoundingClientRect();

  if (!rect) {
    return {
      x: clientX / zoom,
      y: clientY / zoom,
    };
  }

  return {
    x: (clientX - rect.left) / zoom,
    y: (clientY - rect.top) / zoom,
  };
}

function clampZoom(value: number): number {
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

function isCanvasPanTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false;
  }

  return target.closest("[data-graph-node='true'], button") === null;
}

function selectionRectFromState(selection: SelectionState): SelectionRect {
  const left = Math.min(selection.start.x, selection.end.x);
  const top = Math.min(selection.start.y, selection.end.y);
  return {
    left,
    top,
    width: Math.abs(selection.end.x - selection.start.x),
    height: Math.abs(selection.end.y - selection.start.y),
  };
}

function rectsIntersect(a: SelectionRect, b: SelectionRect): boolean {
  return (
    a.left <= b.left + b.width &&
    a.left + a.width >= b.left &&
    a.top <= b.top + b.height &&
    a.top + a.height >= b.top
  );
}

export function GraphCanvas({
  canvasRef,
  descriptors,
  nodes,
  edges,
  selectedNodeIds,
  selectedEdgeId,
  invalidNodeIds,
  pendingConnection,
  isCompatibleInput,
  zoom,
  portPositions,
  registerPort,
  onSelectNode,
  onSelectNodes,
  onToggleNodeSelection,
  onSelectEdge,
  onAddNode,
  onMoveNodes,
  onStartConnection,
  onCompleteConnection,
  onZoomChange,
  onMessage,
}: GraphCanvasProps) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [dragState, setDragState] = useState<NodeDragState | null>(null);
  const [panState, setPanState] = useState<CanvasPanState | null>(null);
  const [selectionState, setSelectionState] = useState<SelectionState | null>(null);
  const zoomAnchorRef = useRef<ZoomAnchor | null>(null);

  const descriptorByType = useMemo(
    () => new Map(descriptors.map((descriptor) => [descriptor.type, descriptor])),
    [descriptors],
  );
  const canvasSize = useMemo(
    () => getCanvasSize(nodes, descriptorByType),
    [nodes, descriptorByType],
  );

  useLayoutEffect(() => {
    const anchor = zoomAnchorRef.current;
    if (anchor === null) {
      return;
    }

    anchor.viewport.scrollLeft = anchor.worldX * zoom - anchor.pointerX;
    anchor.viewport.scrollTop = anchor.worldY * zoom - anchor.pointerY;
    zoomAnchorRef.current = null;
  }, [zoom]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport === null) {
      return undefined;
    }

    function handleNativeWheel(event: globalThis.WheelEvent) {
      event.preventDefault();
      event.stopPropagation();

      const nextZoom = clampZoom(
        event.deltaY < 0 ? zoom * ZOOM_FACTOR : zoom / ZOOM_FACTOR,
      );
      if (nextZoom === zoom || viewport === null) {
        return;
      }

      const rect = viewport.getBoundingClientRect();
      const pointerX = event.clientX - rect.left;
      const pointerY = event.clientY - rect.top;
      const worldX = (viewport.scrollLeft + pointerX) / zoom;
      const worldY = (viewport.scrollTop + pointerY) / zoom;

      zoomAnchorRef.current = {
        viewport,
        pointerX,
        pointerY,
        worldX,
        worldY,
      };
      onZoomChange(nextZoom);
    }

    viewport.addEventListener("wheel", handleNativeWheel, { passive: false });
    return () => {
      viewport.removeEventListener("wheel", handleNativeWheel);
    };
  }, [onZoomChange, zoom]);

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
      getCanvasPoint(canvasRef, event.clientX, event.clientY, zoom),
    );
  }

  function handleNodePointerDown(
    event: ReactMouseEvent<HTMLDivElement>,
    nodeId: NodeId,
  ) {
    event.stopPropagation();
    if (event.button !== 0 || event.target instanceof Element && event.target.closest("button")) {
      return;
    }

    const node = nodes.find((candidate) => candidate.id === nodeId);

    if (!node) {
      return;
    }

    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      onToggleNodeSelection(nodeId);
      return;
    }

    const draggedNodeIds = selectedNodeIds.has(nodeId)
      ? Array.from(selectedNodeIds)
      : [nodeId];
    const startPositions = Object.fromEntries(
      nodes
        .filter((candidate) => draggedNodeIds.includes(candidate.id))
        .map((candidate) => [candidate.id, candidate.position]),
    );

    setDragState({
      nodeIds: draggedNodeIds,
      startPointer: {
        x: event.clientX,
        y: event.clientY,
      },
      startPositions,
    });

    if (!selectedNodeIds.has(nodeId)) {
      onSelectNode(nodeId);
    }
  }

  function handleCanvasMouseDown(event: ReactMouseEvent<HTMLDivElement>) {
    if (event.button !== 0 || !isCanvasPanTarget(event.target)) {
      return;
    }

    event.preventDefault();
    setDragState(null);
    onSelectEdge(null);

    if (event.detail < 2) {
      const point = getCanvasPoint(canvasRef, event.clientX, event.clientY, zoom);
      setSelectionState({ start: point, end: point });
      return;
    }

    setSelectionState(null);
    setPanState({
      startPointer: {
        x: event.clientX,
        y: event.clientY,
      },
      startScrollLeft: event.currentTarget.scrollLeft,
      startScrollTop: event.currentTarget.scrollTop,
    });
    onMessage?.("Canvas grabbed. Move the pointer to pan.");
  }

  function handleMouseMove(event: ReactMouseEvent<HTMLDivElement>) {
    if (panState) {
      if (event.buttons === 0) {
        setPanState(null);
        return;
      }

      const dx = event.clientX - panState.startPointer.x;
      const dy = event.clientY - panState.startPointer.y;
      event.currentTarget.scrollLeft = panState.startScrollLeft - dx;
      event.currentTarget.scrollTop = panState.startScrollTop - dy;
      return;
    }

    if (selectionState) {
      setSelectionState({
        ...selectionState,
        end: getCanvasPoint(canvasRef, event.clientX, event.clientY, zoom),
      });
      return;
    }

    if (!dragState) {
      return;
    }

    const dx = (event.clientX - dragState.startPointer.x) / zoom;
    const dy = (event.clientY - dragState.startPointer.y) / zoom;

    const positions = Object.fromEntries(
      dragState.nodeIds.map((nodeId) => {
        const startPosition = dragState.startPositions[nodeId];
        return [
          nodeId,
          {
            x: Math.max(16, startPosition.x + dx),
            y: Math.max(16, startPosition.y + dy),
          },
        ];
      }),
    );
    onMoveNodes(positions);
  }

  function handleMouseUp(event?: ReactMouseEvent<HTMLDivElement>) {
    if (selectionState) {
      const finalSelection = event
        ? {
            ...selectionState,
            end: getCanvasPoint(canvasRef, event.clientX, event.clientY, zoom),
          }
        : selectionState;
      const rect = selectionRectFromState(finalSelection);
      if (rect.width < 4 && rect.height < 4) {
        onSelectNodes([]);
      } else {
        const selectedIds = nodes
          .filter((node) => {
            const descriptor = descriptorByType.get(node.type);
            if (!descriptor) {
              return false;
            }
            const size = getPreferredNodeSize(descriptor);
            return rectsIntersect(rect, {
              left: node.position.x,
              top: node.position.y,
              width: size.width,
              height: size.height,
            });
          })
          .map((node) => node.id);
        onSelectNodes(selectedIds);
      }
      setSelectionState(null);
    }
    setDragState(null);
    setPanState(null);
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
      ref={viewportRef}
      className={[
        "relative min-h-0 flex-1 overflow-auto",
        panState ? "cursor-grabbing" : "cursor-default",
      ].join(" ")}
      onMouseDown={handleCanvasMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <div
        className="relative"
        style={{
          width: canvasSize.width * zoom,
          height: canvasSize.height * zoom,
        }}
      >
        <div
          ref={canvasRef}
          className="absolute left-0 top-0"
          style={{
            width: canvasSize.width,
            height: canvasSize.height,
            transform: `scale(${zoom})`,
            transformOrigin: "0 0",
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
                Затем выбери выходной порт и подключи его к совместимому входу.
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

          {selectionState && (
            <div
              className="pointer-events-none absolute z-40 border border-sky-500 bg-sky-400/10"
              style={selectionRectFromState(selectionState)}
            />
          )}

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
                selected={selectedNodeIds.has(node.id)}
                invalid={invalidNodeIds.has(node.id)}
                pendingConnectionFrom={pendingConnection?.from ?? null}
                isCompatibleInput={isCompatibleInput}
                onPointerDown={handleNodePointerDown}
                onPortClick={handlePortClick}
                registerPort={registerPort}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
