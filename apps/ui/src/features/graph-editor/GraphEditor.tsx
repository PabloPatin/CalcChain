import type { DragEvent } from "react";
import { useEffect, useRef, useState } from "react";

import { getCatalog } from "../../shared/api/backendApi";
import type {
  BlockDescriptor,
  CanvasPosition,
  GraphNode,
} from "./model/types";

import {
  FALLBACK_BLOCK_DESCRIPTORS,
  resolveBlockDescriptors,
} from "./model/blockDescriptors";
import { mapCatalogResponse, type EditorCatalog } from "./model/catalog";

import { useGraphState } from "./hooks/useGraphState";
import { usePortPositions } from "./hooks/usePortPositions";
import { useConnectionCreation } from "./hooks/useConnectionCreation";

import { BlockPalette } from "./components/BlockPalette";
import { GraphToolbar } from "./components/GraphToolbar";
import { GraphCanvas } from "./components/GraphCanvas";
import { Inspector } from "./components/Inspector";

const BLOCK_DRAG_MIME = "application/x-calcchain-block";

const FALLBACK_CATALOG: EditorCatalog = {
  catalogVersion: "fallback",
  descriptors: resolveBlockDescriptors(FALLBACK_BLOCK_DESCRIPTORS),
  connectionRules: [],
  plugins: [],
};

function getPreferredNodeSize(descriptor: BlockDescriptor) {
  return {
    width: descriptor.defaultSize?.width ?? 252,
    height: descriptor.defaultSize?.height ?? 168,
  };
}

function getVisibleCanvasCenter(
  canvasElement: HTMLDivElement | null,
): CanvasPosition {
  if (!canvasElement) {
    return {
      x: 320,
      y: 220,
    };
  }

  const viewport = canvasElement.parentElement;

  if (!viewport) {
    return {
      x: canvasElement.clientWidth / 2,
      y: canvasElement.clientHeight / 2,
    };
  }

  return {
    x: viewport.scrollLeft + viewport.clientWidth / 2,
    y: viewport.scrollTop + viewport.clientHeight / 2,
  };
}

function getCenteredNodePosition(
  descriptor: BlockDescriptor,
  center: CanvasPosition,
): CanvasPosition {
  const size = getPreferredNodeSize(descriptor);

  return {
    x: Math.max(16, center.x - size.width / 2),
    y: Math.max(16, center.y - size.height / 2),
  };
}

export function GraphEditor() {
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const [message, setMessage] = useState(
    "Поле пустое. Добавь блоки из палитры слева.",
  );
  const [catalog, setCatalog] = useState<EditorCatalog>(FALLBACK_CATALOG);
  const [catalogSource, setCatalogSource] = useState<"backend" | "fallback">("fallback");

  useEffect(() => {
    let cancelled = false;

    async function loadCatalog() {
      try {
        const backendCatalog = await getCatalog();
        if (cancelled) {
          return;
        }

        const editorCatalog = mapCatalogResponse(backendCatalog);
        setCatalog(editorCatalog);
        setCatalogSource("backend");
        setMessage(
          `Каталог загружен: ${editorCatalog.descriptors.length} блоков, ${editorCatalog.plugins.length} плагинов.`,
        );
      } catch (caught) {
        if (cancelled) {
          return;
        }

        setCatalog(FALLBACK_CATALOG);
        setCatalogSource("fallback");
        setMessage(
          `Каталог backend недоступен, используются fallback-блоки. ${
            caught instanceof Error ? caught.message : "Неизвестная ошибка"
          }`,
        );
      }
    }

    void loadCatalog();

    return () => {
      cancelled = true;
    };
  }, []);

  const descriptors = catalog.descriptors;
  const graph = useGraphState();

  const {
    document,
    nodes,
    edges,
    selectedNodeId,
    selectedEdgeId,
    selectedNode,
    selectedEdge,

    selectNode,
    selectEdge,

    addNode,
    moveNode,
    deleteNode,

    addEdge,
    deleteEdge,

    updateNodeData,
    clearGraph,
  } = graph;

  const { portPositions, registerPort } = usePortPositions({
    canvasRef,
    dependencies: [nodes, edges, selectedNodeId, selectedEdgeId],
  });

  const connection = useConnectionCreation({
    nodes,
    edges,
    descriptors,
    connectionRules: catalog.connectionRules,
    onCreateEdge: addEdge,
  });

  function handleAddAtCenter(descriptor: BlockDescriptor): GraphNode {
    const center = getVisibleCanvasCenter(canvasRef.current);
    const position = getCenteredNodePosition(descriptor, center);

    const node = addNode(descriptor, position);
    setMessage(`Добавлен блок: ${descriptor.title}`);

    return node;
  }

  function handlePaletteDragStart(
    event: DragEvent<HTMLButtonElement>,
    descriptor: BlockDescriptor,
  ) {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData(BLOCK_DRAG_MIME, descriptor.type);
    event.dataTransfer.setData("text/plain", descriptor.type);

    setMessage(`Перетащи ${descriptor.title} на рабочую область.`);
  }

  function handleSave() {
    localStorage.setItem("calcchain.graph", JSON.stringify(document, null, 2));
    setMessage("Граф сохранен в localStorage.");
  }

  function handleValidate() {
    if (nodes.length === 0) {
      setMessage("Граф пустой. Добавь хотя бы один блок.");
      return;
    }

    setMessage(
      `Проверка соединений использует правила из ${catalogSource} catalog (${catalog.connectionRules.length}). Backend-валидацию графа подключим следующим шагом.`,
    );
  }

  function handleClear() {
    clearGraph();
    connection.cancelConnection();
    setMessage("Рабочая область очищена.");
  }

  function handleCancelConnection() {
    connection.cancelConnection();
    setMessage("Создание соединения отменено.");
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-slate-100 text-slate-950">
      <BlockPalette
        descriptors={descriptors}
        onAddAtCenter={handleAddAtCenter}
        onDragStart={handlePaletteDragStart}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <GraphToolbar
          message={message}
          isCreatingConnection={connection.isCreatingConnection}
          onSave={handleSave}
          onValidate={handleValidate}
          onClear={handleClear}
          onCancelConnection={handleCancelConnection}
        />

        <GraphCanvas
          canvasRef={canvasRef}
          descriptors={descriptors}
          nodes={nodes}
          edges={edges}
          selectedNodeId={selectedNodeId}
          selectedEdgeId={selectedEdgeId}
          pendingConnection={connection.pendingConnection}
          isCompatibleInput={connection.isCompatibleInput}
          portPositions={portPositions}
          registerPort={registerPort}
          onSelectNode={selectNode}
          onSelectEdge={selectEdge}
          onAddNode={addNode}
          onMoveNode={moveNode}
          onStartConnection={connection.startConnection}
          onCompleteConnection={connection.completeConnection}
          onMessage={setMessage}
        />
      </main>

      <Inspector
        selectedNode={selectedNode}
        selectedEdge={selectedEdge}
        nodes={nodes}
        edges={edges}
        descriptors={descriptors}
        onUpdateNodeData={updateNodeData}
        onDeleteNode={deleteNode}
        onDeleteEdge={deleteEdge}
      />
    </div>
  );
}
