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
    schemaVersion: DEFAULT_SCHEMA_VERSION,
    name,
    nodes: [],
    edges: [],
    viewport: {
      x: 0,
      y: 0,
      zoom: 1,
    },
  };
}

export function createGraphNode(
  descriptor: BlockDescriptor,
  position: CanvasPosition,
): GraphNode {
  return {
    id: createId("node"),
    type: descriptor.type,
    title: descriptor.title,
    position,
    size: descriptor.defaultSize,
    data: {
      ...descriptor.defaultData,
    },
    status: "draft",
  };
}

export function createGraphEdge(
  from: GraphPortEndpoint,
  to: GraphPortEndpoint,
): GraphEdge {
  return {
    id: createId("edge"),
    from,
    to,
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
      const node = createGraphNode(descriptor, position);

      setDocumentState((current) => ({
        ...current,
        nodes: [...current.nodes, node],
      }));

      setSelectedNodeId(node.id);
      setSelectedEdgeId(null);

      return node;
    },
    [],
  );

  const updateNodeData = useCallback(
    (nodeId: NodeId, dataPatch: Partial<BlockData>) => {
      setDocumentState((current) => ({
        ...current,
        nodes: current.nodes.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  ...dataPatch,
                },
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
              data,
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
        (edge) => edge.from.nodeId !== nodeId && edge.to.nodeId !== nodeId,
      ),
    }));

    setSelectedNodeId((current) => (current === nodeId ? null : current));
    setSelectedEdgeId(null);
  }, []);

  const addEdge = useCallback(
    (from: GraphPortEndpoint, to: GraphPortEndpoint): GraphEdge | null => {
      const edgeAlreadyExists = document.edges.some(
        (edge) =>
          edge.from.nodeId === from.nodeId &&
          edge.from.portId === from.portId &&
          edge.to.nodeId === to.nodeId &&
          edge.to.portId === to.portId,
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