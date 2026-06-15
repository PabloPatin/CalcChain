import type { ChangeEvent, DragEvent } from "react";
import { useEffect, useRef, useState } from "react";

import {
  compileGraph,
  createProject,
  createRun,
  getCatalog,
  getRun,
  getRunLogs,
  getSecretRequirements,
  importManifest,
  listProjects,
  listRunArtifacts,
  storeSessionSecret,
  streamRunEvents,
  updateProject,
  validateGraph,
} from "../../shared/api/backendApi";
import type {
  ArtifactSummary,
  BackendGraphDocument,
  LogItem,
  GraphValidateResponse,
  JsonObject,
  Project,
  RunDetails,
  RunEvent,
  RunStatus,
  SecretRequirement,
} from "../../shared/api/backendTypes";
import type {
  BlockDescriptor,
  CanvasPosition,
  GraphDocument,
  GraphNode,
} from "./model/types";

import {
  FALLBACK_BLOCK_DESCRIPTORS,
  resolveBlockDescriptors,
} from "./model/blockDescriptors";
import { mapCatalogResponse, type EditorCatalog } from "./model/catalog";
import { sanitizeGraphSecrets } from "./model/secrets";

import { createEmptyGraphDocument, useGraphState } from "./hooks/useGraphState";
import { usePortPositions } from "./hooks/usePortPositions";
import { useConnectionCreation } from "./hooks/useConnectionCreation";

import { BlockPalette } from "./components/BlockPalette";
import { GraphToolbar } from "./components/GraphToolbar";
import { GraphCanvas } from "./components/GraphCanvas";
import { Inspector } from "./components/Inspector";
import { RunMonitorPanel } from "./components/RunMonitorPanel";
import {
  SecretPromptModal,
  type SecretFormValues,
} from "./components/SecretPromptModal";
import { ProjectLoadDialog } from "./components/ProjectLoadDialog";

const BLOCK_DRAG_MIME = "application/x-calcchain-block";
const RUN_POLL_INTERVAL_MS = 2_000;

const FALLBACK_CATALOG: EditorCatalog = {
  catalogVersion: "fallback",
  descriptors: resolveBlockDescriptors(FALLBACK_BLOCK_DESCRIPTORS),
  connectionRules: [],
  plugins: [],
};

interface SecretPromptState {
  graph: GraphDocument;
  requirements: SecretRequirement[];
  values: SecretFormValues;
}

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
  const manifestInputRef = useRef<HTMLInputElement | null>(null);
  const [message, setMessage] = useState(
    "Рабочая область пустая. Добавьте блоки из палитры слева.",
  );
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("Новый граф расчёта");
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [savedProjects, setSavedProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [catalog, setCatalog] = useState<EditorCatalog>(FALLBACK_CATALOG);
  const [catalogSource, setCatalogSource] = useState<"backend" | "fallback">("fallback");
  const [busyAction, setBusyAction] = useState<"validate" | "compile-run" | "import" | null>(null);
  const [secretPrompt, setSecretPrompt] = useState<SecretPromptState | null>(null);
  const [canvasZoom, setCanvasZoom] = useState(1);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<RunDetails | null>(null);
  const [runEvents, setRunEvents] = useState<RunEvent[]>([]);
  const [runLogs, setRunLogs] = useState<LogItem[]>([]);
  const [runArtifacts, setRunArtifacts] = useState<ArtifactSummary[]>([]);
  const [validationDebug, setValidationDebug] = useState<unknown | null>(null);
  const [validationIssueNodeIds, setValidationIssueNodeIds] = useState<Set<string>>(new Set());

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
          `Каталог backend недоступен, используются резервные блоки. ${
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

  useEffect(() => {
    if (activeRunId === null) {
      return;
    }

    const runId = activeRunId;
    let cancelled = false;
    const abortController = new AbortController();

    async function refreshRun(includeArtifacts: boolean) {
      try {
        const [details, logs] = await Promise.all([
          getRun(runId),
          getRunLogs(runId),
        ]);
        if (cancelled) {
          return;
        }

        setRunDetails(details);
        setRunLogs(logs.items);

        if (isTerminalRunStatus(details.status)) {
          const artifacts = await listRunArtifacts(runId);
          if (!cancelled) {
            setRunArtifacts(artifacts.items);
          }
          return;
        }

        if (includeArtifacts) {
          const artifacts = await listRunArtifacts(runId);
          if (!cancelled) {
            setRunArtifacts(artifacts.items);
          }
        }
      } catch (caught) {
        if (!cancelled) {
          setMessage(
            `Не удалось обновить состояние расчёта: ${
              caught instanceof Error ? caught.message : "неизвестная ошибка"
            }`,
          );
        }
      }
    }

    void refreshRun(true);
    void streamRunEvents(
      runId,
      (event) => {
        setRunEvents((current) => [...current.slice(-99), event]);
      },
      { signal: abortController.signal },
    ).catch((caught) => {
      if (!abortController.signal.aborted) {
        setMessage(
          `Поток событий недоступен, используется опрос: ${
            caught instanceof Error ? caught.message : "неизвестная ошибка"
          }`,
        );
      }
    });

    const intervalId = window.setInterval(() => {
      void refreshRun(false);
    }, RUN_POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      abortController.abort();
      window.clearInterval(intervalId);
    };
  }, [activeRunId]);

  const descriptors = catalog.descriptors;
  const graph = useGraphState();

  const {
    document,
    nodes,
    edges,
    selectedNodeId,
    selectedNodeIds,
    selectedEdgeId,
    selectedNode,
    selectedEdge,

    setDocument,

    selectNode,
    selectNodes,
    toggleNodeSelection,
    selectEdge,

    addNode,
    moveNodes,
    deleteNode,
    deleteNodes,

    addEdge,
    deleteEdge,

    updateNodeData,
  } = graph;

  const { portPositions, registerPort } = usePortPositions({
    canvasRef,
    scale: canvasZoom,
    dependencies: [nodes, edges, selectedNodeId, selectedEdgeId, canvasZoom],
  });

  const connection = useConnectionCreation({
    nodes,
    edges,
    descriptors,
    connectionRules: catalog.connectionRules,
    onCreateEdge: addEdge,
  });

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Delete" || isTypingTarget(event.target)) {
        return;
      }

      if (selectedEdgeId !== null) {
        event.preventDefault();
        deleteEdge(selectedEdgeId);
        setMessage("Выбранное соединение удалено.");
        return;
      }

      if (selectedNodeIds.size > 0) {
        event.preventDefault();
        const nodeCount = selectedNodeIds.size;
        deleteNodes(Array.from(selectedNodeIds));
        setMessage(nodeCount === 1 ? "Выбранный блок удалён." : `Выбранные блоки удалены: ${nodeCount}.`);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [deleteEdge, deleteNodes, selectedEdgeId, selectedNodeIds]);

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

    setMessage(`Перетащите ${descriptor.title} на рабочую область.`);
  }

  function handleSelectNode(nodeId: string | null) {
    if (nodeId !== null) {
      setValidationDebug(null);
    }
    selectNode(nodeId);
  }

  function handleNewProject() {
    const next = createEmptyGraphDocument();
    setDocument(next);
    connection.cancelConnection();
    setActiveProjectId(null);
    setProjectName(next.name);
    setValidationDebug(null);
    setValidationIssueNodeIds(new Set());
    setMessage("Создан новый проект.");
  }

  async function handleSave() {
    const name = projectName.trim();
    if (!name) {
      setMessage("Перед сохранением укажите название проекта.");
      return;
    }

    const safeGraph = graphWithName(sanitizeGraphSecrets(document, descriptors), name);
    setProjectBusy(true);
    setMessage("Сохранение проекта...");
    try {
      const saved = activeProjectId === null
        ? await createProject({ name, graph: safeGraph })
        : await updateProject(activeProjectId, { name, graph: safeGraph });
      const loadedGraph = graphFromProject(saved);
      setDocument(loadedGraph);
      setActiveProjectId(saved.id);
      setProjectName(saved.name);
      setMessage(`Проект сохранён: ${saved.name}`);
    } catch (caught) {
      setMessage(`Не удалось сохранить проект: ${caught instanceof Error ? caught.message : "неизвестная ошибка"}`);
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleLoad() {
    setProjectDialogOpen(true);
    setProjectsLoading(true);
    setProjectBusy(true);
    setMessage("Загрузка списка проектов...");
    try {
      const result = await listProjects();
      setSavedProjects(result.items);
      setMessage(`Проекты загружены: ${result.items.length}.`);
    } catch (caught) {
      setSavedProjects([]);
      setMessage(`Не удалось загрузить список проектов: ${caught instanceof Error ? caught.message : "неизвестная ошибка"}`);
    } finally {
      setProjectsLoading(false);
      setProjectBusy(false);
    }
  }

  /*
    const rawGraph = localStorage.getItem(GRAPH_STORAGE_KEY);
    if (rawGraph === null) {
      setMessage("Сохраненный граф не найден.");
      return;
    }

    try {
      const graphDocument = JSON.parse(rawGraph) as GraphDocument;
      if (!isGraphDocumentLike(graphDocument)) {
        setMessage("Сохраненный граф имеет неподдерживаемый формат.");
        return;
      }

      const safeGraph = sanitizeGraphSecrets(graphDocument, descriptors);
      setDocument(safeGraph);
      connection.cancelConnection();
      setMessage(`Граф загружен: ${safeGraph.nodes.length} блоков.`);
    } catch (caught) {
      setMessage(
        `Не удалось загрузить граф: ${
          caught instanceof Error ? caught.message : "неизвестная ошибка"
        }`,
      );
    }
  }

    */

  function handleLoadProject(project: Project) {
    const loadedGraph = graphFromProject(project);
    setDocument(loadedGraph);
    connection.cancelConnection();
    setActiveProjectId(project.id);
    setProjectName(project.name);
    setProjectDialogOpen(false);
    setValidationDebug(null);
    setValidationIssueNodeIds(new Set());
    setMessage(`Проект загружен: ${project.name}`);
  }

  function handleImportManifestClick() {
    manifestInputRef.current?.click();
  }

  function handleManifestInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (file === null) {
      return;
    }
    void handleImportManifestFile(file);
  }

  async function handleImportManifestFile(file: File, position?: CanvasPosition) {
    if (!file.name.toLowerCase().endsWith(".json")) {
      setMessage("Не удалось импортировать manifest: выберите файл .json.");
      return;
    }

    setBusyAction("import");
    setValidationDebug(null);
    setValidationIssueNodeIds(new Set());
    setMessage(`Импорт manifest: ${file.name}...`);

    try {
      const result = await importManifest(file);
      if (!result.valid || !result.graph) {
        setValidationDebug(result);
        setMessage(
          `Не удалось импортировать manifest: ${result.diagnostics[0]?.message ?? "неизвестная ошибка manifest"}`,
        );
        return;
      }

      const anchor = position ?? getFreeImportPosition(document.nodes, descriptors, canvasRef.current);
      const merged = mergeImportedGraph(document, result.graph, anchor, result.environment?.import_id);
      setDocument(merged.document);
      selectNodes(merged.importedNodeIds);
      connection.cancelConnection();
      setValidationDebug(result);

      const calculationCount = merged.document.nodes.filter((node) => node.type === "calculation").length;
      const warningText = result.warnings.length > 0 ? ` Предупреждений: ${result.warnings.length}.` : "";
      const calculationText = calculationCount > 1
        ? " Проверка покажет ошибку о нескольких нодах «Расчёт», пока в графе не останется только одна такая нода."
        : "";
      const environmentText = result.environment?.target_job_dir
        ? ` Окружение: ${result.environment.target_job_dir}.`
        : "";
      setMessage(
        `Manifest импортирован: добавлено нод: ${merged.importedNodeIds.length}.${environmentText}${warningText}${calculationText}`,
      );
    } catch (caught) {
      setMessage(
        `Не удалось импортировать manifest: ${caught instanceof Error ? caught.message : "неизвестная ошибка"}`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleValidate() {
    if (nodes.length === 0) {
      setMessage("Граф пустой. Добавьте хотя бы один блок.");
      return;
    }

    const safeGraph = graphWithName(sanitizeGraphSecrets(document, descriptors), projectName.trim() || document.name);
    setDocument(safeGraph);
    setBusyAction("validate");
    setValidationDebug(null);
    setValidationIssueNodeIds(new Set());
    setMessage("Проверка графа...");
    try {
      const result = await validateGraph(safeGraph);
      if (result.valid) {
        setMessage(
          `Проверка backend пройдена: каталог ${catalogSource}, правил соединений: ${catalog.connectionRules.length}.`,
        );
        return;
      }

      setValidationDebug(result);
      setValidationIssueNodeIds(getValidationIssueNodeIds(result));
      setMessage(
        `Проверка backend не пройдена: ${result.errors[0]?.message ?? "неизвестная ошибка графа"}`,
      );
    } catch (caught) {
      setValidationIssueNodeIds(new Set());
      setValidationDebug({
        error: caught instanceof Error ? caught.message : "неизвестная ошибка",
      });
      setMessage(
        `Проверка backend недоступна: ${
          caught instanceof Error ? caught.message : "неизвестная ошибка"
        }`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCompileRun() {
    if (nodes.length === 0) {
      setMessage("Граф пустой. Добавьте хотя бы один блок.");
      return;
    }

    const safeGraph = graphWithName(sanitizeGraphSecrets(document, descriptors), projectName.trim() || document.name);
    setDocument(safeGraph);
    setBusyAction("compile-run");
    setMessage("Проверка секретов...");
    try {
      const requirements = await getSecretRequirements({ graph: safeGraph });
      const pendingRequirements = requirements.requirements.filter(
        (requirement) =>
          (requirement.status === "missing" || requirement.status === "partial") &&
          requirement.fields.some((field) => field.secret),
      );

      if (pendingRequirements.length > 0) {
        setSecretPrompt({
          graph: safeGraph,
          requirements: pendingRequirements,
          values: createSecretValues(pendingRequirements, document),
        });
        setMessage(`Нужно заполнить секреты: ${pendingRequirements.length}.`);
        return;
      }

      await compileAndRun(safeGraph);
    } catch (caught) {
      setMessage(
        `Не удалось собрать и запустить: ${
          caught instanceof Error ? caught.message : "неизвестная ошибка"
        }`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  function handleSecretChange(secretRef: string, fieldName: string, value: string) {
    setSecretPrompt((current) => {
      if (current === null) {
        return current;
      }

      return {
        ...current,
        values: {
          ...current.values,
          [secretRef]: {
            ...current.values[secretRef],
            [fieldName]: value,
          },
        },
      };
    });
  }

  async function handleSecretSubmit() {
    if (secretPrompt === null) {
      return;
    }

    setBusyAction("compile-run");
    try {
      for (const requirement of secretPrompt.requirements) {
        const values = secretPrompt.values[requirement.secret_ref] ?? {};
        await storeSessionSecret({
          secret_ref: requirement.secret_ref,
          kind: requirement.kind,
          values,
        });
      }

      const graphWithoutSecrets = graphWithName(
        sanitizeGraphSecrets(secretPrompt.graph, descriptors),
        projectName.trim() || secretPrompt.graph.name,
      );
      setDocument(graphWithoutSecrets);
      setSecretPrompt(null);
      await compileAndRun(graphWithoutSecrets);
    } catch (caught) {
      setMessage(
        `Не удалось собрать и запустить: ${
          caught instanceof Error ? caught.message : "неизвестная ошибка"
        }`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function compileAndRun(graphDocument: GraphDocument) {
    setMessage("Сборка графа...");
    const compileResult = await compileGraph(graphDocument);
    if (!compileResult.valid) {
      setMessage(
        `Сборка не выполнена: ${compileResult.diagnostics[0]?.message ?? "неизвестная ошибка графа"}`,
      );
      return;
    }

    setMessage("Сборка пройдена. Запуск расчёта...");
    const run = await createRun(compileResult);
    setActiveRunId(run.run_id);
    setRunDetails(null);
    setRunEvents([]);
    setRunLogs([]);
    setRunArtifacts([]);
    setMessage(`Расчёт ${run.run_id} запущен, статус: ${run.status}.`);
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
          busyAction={busyAction}
          projectBusy={projectBusy}
          projectName={projectName}
          activeProjectId={activeProjectId}
          onProjectNameChange={setProjectName}
          onNewProject={handleNewProject}
          onSave={handleSave}
          onLoad={handleLoad}
          onImportManifest={handleImportManifestClick}
          onValidate={handleValidate}
          onCompileRun={handleCompileRun}
        />

        <input
          ref={manifestInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={handleManifestInputChange}
        />

        <RunMonitorPanel
          run={runDetails}
          events={runEvents}
          logs={runLogs}
          artifacts={runArtifacts}
        />

        <GraphCanvas
          canvasRef={canvasRef}
          descriptors={descriptors}
          nodes={nodes}
          edges={edges}
          selectedNodeIds={selectedNodeIds}
          selectedEdgeId={selectedEdgeId}
          invalidNodeIds={validationIssueNodeIds}
          pendingConnection={connection.pendingConnection}
          isCompatibleInput={connection.isCompatibleInput}
          zoom={canvasZoom}
          portPositions={portPositions}
          registerPort={registerPort}
          onSelectNode={handleSelectNode}
          onSelectNodes={selectNodes}
          onToggleNodeSelection={toggleNodeSelection}
          onSelectEdge={selectEdge}
          onAddNode={addNode}
          onMoveNodes={moveNodes}
          onStartConnection={connection.startConnection}
          onCompleteConnection={connection.completeConnection}
          onZoomChange={setCanvasZoom}
          onMessage={setMessage}
          onImportManifestFile={handleImportManifestFile}
        />
      </main>

      <Inspector
        selectedNode={selectedNode}
        selectedEdge={selectedEdge}
        validationDebug={validationDebug}
        nodes={nodes}
        edges={edges}
        descriptors={descriptors}
        onUpdateNodeData={updateNodeData}
        onDeleteNode={deleteNode}
        onDeleteEdge={deleteEdge}
      />

      {secretPrompt && (
        <SecretPromptModal
          requirements={secretPrompt.requirements}
          values={secretPrompt.values}
          submitting={busyAction === "compile-run"}
          onChange={handleSecretChange}
          onSubmit={handleSecretSubmit}
          onCancel={() => setSecretPrompt(null)}
        />
      )}

      {projectDialogOpen && (
        <ProjectLoadDialog
          projects={savedProjects}
          loading={projectsLoading}
          onLoad={handleLoadProject}
          onClose={() => setProjectDialogOpen(false)}
        />
      )}
    </div>
  );
}

function isTerminalRunStatus(status: RunStatus): boolean {
  return status === "success" || status === "failed" || status === "cancelled";
}

function getValidationIssueNodeIds(result: GraphValidateResponse): Set<string> {
  const nodeIds = new Set<string>();
  for (const diagnostic of result.errors) {
    if (diagnostic.node_id) {
      nodeIds.add(diagnostic.node_id);
    }
  }
  return nodeIds;
}

function createSecretValues(
  requirements: SecretRequirement[],
  graph: GraphDocument,
): SecretFormValues {
  const values: SecretFormValues = {};
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  for (const requirement of requirements) {
    values[requirement.secret_ref] = {};
    const sourceNode = requirement.used_by
      .map((usage) => nodesById.get(usage.node_id))
      .find((node) => node !== undefined);
    for (const field of requirement.fields) {
      if (field.secret) {
        const rawValue = sourceNode?.config[field.config_path ?? field.name];
        values[requirement.secret_ref][field.name] =
          typeof rawValue === "string" ? rawValue : "";
      }
    }
  }
  return values;
}

function graphWithName(graph: GraphDocument, name: string): GraphDocument {
  return {
    ...graph,
    name,
  };
}

function graphFromProject(project: Project): GraphDocument {
  const graph = project.graph;
  return {
    schema_version: graph.schema_version ?? "1.0",
    name: graph.name ?? project.name,
    nodes: graph.nodes.map((node, index) => ({
      id: node.id,
      type: node.type,
      title: node.title ?? node.type,
      position: node.position ?? { x: 80 + index * 32, y: 80 + index * 32 },
      config: node.config,
    })),
    edges: graph.edges,
    metadata: graph.metadata,
  };
}

interface MergeImportedGraphResult {
  document: GraphDocument;
  importedNodeIds: string[];
}

function mergeImportedGraph(
  current: GraphDocument,
  imported: BackendGraphDocument,
  anchor: CanvasPosition,
  importId?: string,
): MergeImportedGraphResult {
  const normalizedImport = graphFromBackendDocument(imported);
  const prefix = safeGraphIdPart(importId || `manifest_${Date.now()}`);
  const existingNodeIds = new Set(current.nodes.map((node) => node.id));
  const existingEdgeIds = new Set(current.edges.map((edge) => edge.id));
  const usedNodeIds = new Set(existingNodeIds);
  const usedEdgeIds = new Set(existingEdgeIds);
  const nodeIdMap = new Map<string, string>();

  for (const node of normalizedImport.nodes) {
    const nextId = uniqueImportedId(`${prefix}_${safeGraphIdPart(node.id)}`, usedNodeIds);
    usedNodeIds.add(nextId);
    nodeIdMap.set(node.id, nextId);
  }

  const bounds = getGraphBounds(normalizedImport.nodes);
  const dx = Math.max(16, anchor.x) - bounds.left;
  const dy = Math.max(16, anchor.y) - bounds.top;
  const importedNodes = normalizedImport.nodes.map((node) => ({
    ...node,
    id: nodeIdMap.get(node.id) ?? node.id,
    position: {
      x: Math.max(16, node.position.x + dx),
      y: Math.max(16, node.position.y + dy),
    },
  }));
  const importedNodeIds = importedNodes.map((node) => node.id);

  const importedEdges = normalizedImport.edges
    .map((edge) => {
      const sourceNodeId = nodeIdMap.get(edge.source.node_id);
      const targetNodeId = nodeIdMap.get(edge.target.node_id);
      if (!sourceNodeId || !targetNodeId) {
        return null;
      }
      const edgeId = uniqueImportedId(`${prefix}_${safeGraphIdPart(edge.id)}`, usedEdgeIds);
      usedEdgeIds.add(edgeId);
      return {
        ...edge,
        id: edgeId,
        source: {
          ...edge.source,
          node_id: sourceNodeId,
        },
        target: {
          ...edge.target,
          node_id: targetNodeId,
        },
      };
    })
    .filter((edge): edge is GraphDocument["edges"][number] => edge !== null);

  const importedMetadata = isJsonObject(imported.metadata) ? imported.metadata : {};
  const importRecord = isJsonObject(importedMetadata.manifest_import)
    ? importedMetadata.manifest_import
    : { import_id: prefix };
  const importHistory = getImportHistory(current.metadata);
  const metadata: JsonObject = {
    ...(current.metadata ?? {}),
    last_manifest_import: importRecord,
    manifest_imports: [...importHistory, importRecord],
  };

  return {
    document: {
      ...current,
      nodes: [...current.nodes, ...importedNodes],
      edges: [...current.edges, ...importedEdges],
      metadata,
    },
    importedNodeIds,
  };
}

function graphFromBackendDocument(graph: BackendGraphDocument): GraphDocument {
  return {
    schema_version: graph.schema_version ?? "1.0",
    name: graph.name ?? "Импортированный manifest",
    nodes: graph.nodes.map((node, index) => ({
      id: node.id,
      type: node.type,
      title: node.title ?? node.type,
      position: node.position ?? { x: 80 + index * 32, y: 80 + index * 32 },
      config: node.config,
    })),
    edges: graph.edges,
    metadata: graph.metadata,
  };
}

function getFreeImportPosition(
  nodes: GraphNode[],
  descriptors: BlockDescriptor[],
  canvasElement: HTMLDivElement | null,
): CanvasPosition {
  if (nodes.length === 0) {
    const center = getVisibleCanvasCenter(canvasElement);
    return { x: Math.max(16, center.x - 180), y: Math.max(16, center.y - 120) };
  }

  let right = 80;
  let top = Number.POSITIVE_INFINITY;
  for (const node of nodes) {
    const descriptor = descriptors.find((candidate) => candidate.type === node.type);
    const size = descriptor ? getPreferredNodeSize(descriptor) : { width: 252, height: 168 };
    right = Math.max(right, node.position.x + size.width);
    top = Math.min(top, node.position.y);
  }

  return {
    x: right + 320,
    y: Number.isFinite(top) ? Math.max(80, top) : 80,
  };
}

function getGraphBounds(nodes: GraphNode[]): { left: number; top: number } {
  if (nodes.length === 0) {
    return { left: 0, top: 0 };
  }

  return {
    left: Math.min(...nodes.map((node) => node.position.x)),
    top: Math.min(...nodes.map((node) => node.position.y)),
  };
}

function uniqueImportedId(base: string, usedIds: Set<string>): string {
  let candidate = base;
  for (let index = 2; usedIds.has(candidate); index += 1) {
    candidate = `${base}_${index}`;
  }
  return candidate;
}

function safeGraphIdPart(value: string): string {
  const normalized = value.replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");
  return normalized || "import";
}

function getImportHistory(metadata: JsonObject | undefined): JsonObject[] {
  const rawHistory = metadata?.manifest_imports;
  return Array.isArray(rawHistory) ? rawHistory.filter(isJsonObject) : [];
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.closest("input, textarea, select, [contenteditable='true']") !== null;
}
