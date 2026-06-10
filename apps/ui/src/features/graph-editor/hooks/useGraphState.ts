import { useCallback, useMemo, useState } from "react";

import type {
  BlockDescriptor,
  BlockData,
  CanvasPosition,
  EdgeId,
  GraphDocument,
  GraphEdge,
  GraphNode,
  GraphPortEndpoint,
  NodeId,
} from "../model/types";

const DEFAULT_GRAPH_NAME = "Untitled calculation graph";
const DEFAULT_SCHEMA_VERSION = "1.0";

function createId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createEmptyGraphDocument(
  name = DEFAULT_GRAPH_NAME,
): GraphDocument {
  return {
    schema_version: DEFAULT_SCHEMA_VERSION,
    name,
    nodes: [],
    edges: [],
  };
}

function mergeBlockData(current: BlockData, patch: Partial<BlockData>): BlockData {
  const next: BlockData = { ...current };
  for (const [key, value] of Object.entries(patch)) {
    if (value !== undefined) {
      next[key] = value;
    }
  }
  return next;
}

export function createGraphNode(
  descriptor: BlockDescriptor,
  position: CanvasPosition,
  title = descriptor.title,
): GraphNode {
  return {
    id: createId("node"),
    type: descriptor.type,
    title,
    position,
    config: {
      ...descriptor.defaultData,
    },
  };
}

function uniqueNodeTitle(descriptor: BlockDescriptor, nodes: GraphNode[]): string {
  const sameTypeTitles = new Set(
    nodes
      .filter((node) => node.type === descriptor.type)
      .map((node) => node.title),
  );

  if (!sameTypeTitles.has(descriptor.title)) {
    return descriptor.title;
  }

  for (let index = 2; ; index += 1) {
    const candidate = `${descriptor.title} ${index}`;
    if (!sameTypeTitles.has(candidate)) {
      return candidate;
    }
  }
}

export function createGraphEdge(
  from: GraphPortEndpoint,
  to: GraphPortEndpoint,
): GraphEdge {
  return {
    id: createId("edge"),
    source: from,
    target: to,
  };
}

export interface UseGraphStateResult {
  document: GraphDocument;
  nodes: GraphNode[];
  edges: GraphEdge[];

  selectedNodeId: NodeId | null;
  selectedEdgeId: EdgeId | null;

  selectedNode: GraphNode | null;
  selectedEdge: GraphEdge | null;

  setDocument: (document: GraphDocument) => void;
  clearGraph: () => void;

  selectNode: (nodeId: NodeId | null) => void;
  selectEdge: (edgeId: EdgeId | null) => void;

  addNode: (descriptor: BlockDescriptor, position: CanvasPosition) => GraphNode;
  updateNodeData: (nodeId: NodeId, dataPatch: Partial<BlockData>) => void;
  replaceNodeData: (nodeId: NodeId, data: BlockData) => void;
  moveNode: (nodeId: NodeId, position: CanvasPosition) => void;
  deleteNode: (nodeId: NodeId) => void;

  addEdge: (from: GraphPortEndpoint, to: GraphPortEndpoint) => GraphEdge | null;
  deleteEdge: (edgeId: EdgeId) => void;
}

export function useGraphState(
  initialDocument?: GraphDocument,
): UseGraphStateResult {
  const [document, setDocumentState] = useState<GraphDocument>(
    initialDocument ?? createEmptyGraphDocument(),
  );

  const [selectedNodeId, setSelectedNodeId] = useState<NodeId | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<EdgeId | null>(null);

  const nodes = document.nodes;
  const edges = document.edges;

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) {
      return null;
    }

    return nodes.find((node) => node.id === selectedNodeId) ?? null;
  }, [nodes, selectedNodeId]);

  const selectedEdge = useMemo(() => {
    if (!selectedEdgeId) {
      return null;
    }

    return edges.find((edge) => edge.id === selectedEdgeId) ?? null;
  }, [edges, selectedEdgeId]);

  const setDocument = useCallback((nextDocument: GraphDocument) => {
    setDocumentState(nextDocument);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const clearGraph = useCallback(() => {
    setDocumentState((current) => ({
      ...current,
      nodes: [],
      edges: [],
    }));

    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const selectNode = useCallback((nodeId: NodeId | null) => {
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
  }, []);

  const selectEdge = useCallback((edgeId: EdgeId | null) => {
    setSelectedEdgeId(edgeId);
    setSelectedNodeId(null);
  }, []);

  const addNode = useCallback(
    (descriptor: BlockDescriptor, position: CanvasPosition): GraphNode => {
      const node = createGraphNode(
        descriptor,
        position,
        uniqueNodeTitle(descriptor, document.nodes),
      );

      setDocumentState((current) => ({
        ...current,
        nodes: [...current.nodes, node],
      }));

      setSelectedNodeId(node.id);
      setSelectedEdgeId(null);

      return node;
    },
    [document.nodes],
  );

  const updateNodeData = useCallback(
    (nodeId: NodeId, dataPatch: Partial<BlockData>) => {
      setDocumentState((current) => ({
        ...current,
        nodes: current.nodes.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                config: mergeBlockData(node.config, dataPatch),
              }
            : node,
        ),
      }));
    },
    [],
  );

  const replaceNodeData = useCallback((nodeId: NodeId, data: BlockData) => {
    setDocumentState((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              config: data,
            }
          : node,
      ),
    }));
  }, []);

  const moveNode = useCallback((nodeId: NodeId, position: CanvasPosition) => {
    setDocumentState((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              position,
            }
          : node,
      ),
    }));
  }, []);

  const deleteNode = useCallback((nodeId: NodeId) => {
    setDocumentState((current) => ({
      ...current,
      nodes: current.nodes.filter((node) => node.id !== nodeId),
      edges: current.edges.filter(
        (edge) => edge.source.node_id !== nodeId && edge.target.node_id !== nodeId,
      ),
    }));

    setSelectedNodeId((current) => (current === nodeId ? null : current));
    setSelectedEdgeId(null);
  }, []);

  const addEdge = useCallback(
    (from: GraphPortEndpoint, to: GraphPortEndpoint): GraphEdge | null => {
      const edgeAlreadyExists = document.edges.some(
        (edge) =>
          edge.source.node_id === from.node_id &&
          edge.source.port_id === from.port_id &&
          edge.target.node_id === to.node_id &&
          edge.target.port_id === to.port_id,
      );

      if (edgeAlreadyExists) {
        return null;
      }

      const edge = createGraphEdge(from, to);

      setDocumentState((current) => ({
        ...current,
        edges: [...current.edges, edge],
      }));

      setSelectedEdgeId(edge.id);
      setSelectedNodeId(null);

      return edge;
    },
    [document.edges],
  );

  const deleteEdge = useCallback((edgeId: EdgeId) => {
    setDocumentState((current) => ({
      ...current,
      edges: current.edges.filter((edge) => edge.id !== edgeId),
    }));

    setSelectedEdgeId((current) => (current === edgeId ? null : current));
  }, []);

  return {
    document,
    nodes,
    edges,

    selectedNodeId,
    selectedEdgeId,

    selectedNode,
    selectedEdge,

    setDocument,
    clearGraph,

    selectNode,
    selectEdge,

    addNode,
    updateNodeData,
    replaceNodeData,
    moveNode,
    deleteNode,

    addEdge,
    deleteEdge,
  };
}
