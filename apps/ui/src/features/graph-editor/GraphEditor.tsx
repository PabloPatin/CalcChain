import type { DragEvent } from "react";
import { useEffect, useRef, useState } from "react";

import {
  compileGraph,
  createProject,
  createRun,
  getCatalog,
  getRun,
  getRunLogs,
  getSecretRequirements,
  listProjects,
  listRunArtifacts,
  storeSessionSecret,
  streamRunEvents,
  updateProject,
  validateGraph,
} from "../../shared/api/backendApi";
import type {
  ArtifactSummary,
  LogItem,
  GraphValidateResponse,
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
  const [message, setMessage] = useState(
    "Поле пустое. Добавь блоки из палитры слева.",
  );
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("Untitled calculation graph");
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectDialogOpen, setProjectDialogOpen] = useState(false);
  const [savedProjects, setSavedProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [catalog, setCatalog] = useState<EditorCatalog>(FALLBACK_CATALOG);
  const [catalogSource, setCatalogSource] = useState<"backend" | "fallback">("fallback");
  const [busyAction, setBusyAction] = useState<"validate" | "compile-run" | null>(null);
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
            `Run polling failed: ${
              caught instanceof Error ? caught.message : "unknown error"
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
          `Run event stream unavailable, polling is active: ${
            caught instanceof Error ? caught.message : "unknown error"
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
        setMessage("Selected connection deleted.");
        return;
      }

      if (selectedNodeIds.size > 0) {
        event.preventDefault();
        const nodeCount = selectedNodeIds.size;
        deleteNodes(Array.from(selectedNodeIds));
        setMessage(nodeCount === 1 ? "Selected node deleted." : `${nodeCount} selected nodes deleted.`);
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

    setMessage(`Перетащи ${descriptor.title} на рабочую область.`);
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
    setMessage("New project started.");
  }

  async function handleSave() {
    const name = projectName.trim();
    if (!name) {
      setMessage("Project name is required before saving.");
      return;
    }

    const safeGraph = graphWithName(sanitizeGraphSecrets(document, descriptors), name);
    setProjectBusy(true);
    setMessage("Saving project...");
    try {
      const saved = activeProjectId === null
        ? await createProject({ name, graph: safeGraph })
        : await updateProject(activeProjectId, { name, graph: safeGraph });
      const loadedGraph = graphFromProject(saved);
      setDocument(loadedGraph);
      setActiveProjectId(saved.id);
      setProjectName(saved.name);
      setMessage(`Project saved: ${saved.name}`);
    } catch (caught) {
      setMessage(`Project save failed: ${caught instanceof Error ? caught.message : "unknown error"}`);
    } finally {
      setProjectBusy(false);
    }
  }

  async function handleLoad() {
    setProjectDialogOpen(true);
    setProjectsLoading(true);
    setProjectBusy(true);
    setMessage("Loading project list...");
    try {
      const result = await listProjects();
      setSavedProjects(result.items);
      setMessage(`Projects loaded: ${result.items.length}`);
    } catch (caught) {
      setSavedProjects([]);
      setMessage(`Project list failed: ${caught instanceof Error ? caught.message : "unknown error"}`);
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
          caught instanceof Error ? caught.message : "unknown error"
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
    setMessage(`Project loaded: ${project.name}`);
  }

  async function handleValidate() {
    if (nodes.length === 0) {
      setMessage("Граф пустой. Добавь хотя бы один блок.");
      return;
    }

    const safeGraph = graphWithName(sanitizeGraphSecrets(document, descriptors), projectName.trim() || document.name);
    setDocument(safeGraph);
    setBusyAction("validate");
    setValidationDebug(null);
    setValidationIssueNodeIds(new Set());
    setMessage("Validating graph...");
    try {
      const result = await validateGraph(safeGraph);
      if (result.valid) {
        setMessage(
          `Backend validation passed (${catalogSource} catalog, ${catalog.connectionRules.length} connection rules).`,
        );
        return;
      }

      setValidationDebug(result);
      setValidationIssueNodeIds(getValidationIssueNodeIds(result));
      setMessage(
        `Backend validation failed: ${result.errors[0]?.message ?? "unknown graph error"}`,
      );
    } catch (caught) {
      setValidationIssueNodeIds(new Set());
      setValidationDebug({
        error: caught instanceof Error ? caught.message : "unknown error",
      });
      setMessage(
        `Backend validation unavailable: ${
          caught instanceof Error ? caught.message : "unknown error"
        }`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleCompileRun() {
    if (nodes.length === 0) {
      setMessage("Граф пустой. Добавь хотя бы один блок.");
      return;
    }

    const safeGraph = graphWithName(sanitizeGraphSecrets(document, descriptors), projectName.trim() || document.name);
    setDocument(safeGraph);
    setBusyAction("compile-run");
    setMessage("Checking secrets...");
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
        `Compile + Run failed: ${
          caught instanceof Error ? caught.message : "unknown error"
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
        `Compile + Run failed: ${
          caught instanceof Error ? caught.message : "unknown error"
        }`,
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function compileAndRun(graphDocument: GraphDocument) {
    setMessage("Compiling graph...");
    const compileResult = await compileGraph(graphDocument);
    if (!compileResult.valid) {
      setMessage(
        `Compile failed: ${compileResult.diagnostics[0]?.message ?? "unknown graph error"}`,
      );
      return;
    }

    setMessage("Compile passed. Starting run...");
    const run = await createRun(compileResult);
    setActiveRunId(run.run_id);
    setRunDetails(null);
    setRunEvents([]);
    setRunLogs([]);
    setRunArtifacts([]);
    setMessage(`Run ${run.run_id} started with status: ${run.status}.`);
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
          onValidate={handleValidate}
          onCompileRun={handleCompileRun}
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

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.closest("input, textarea, select, [contenteditable='true']") !== null;
}
