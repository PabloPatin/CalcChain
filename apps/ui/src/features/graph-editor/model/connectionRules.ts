import type {
  BlockDescriptor,
  ConnectionCheckResult,
  GraphEdge,
  GraphNode,
  GraphPortEndpoint,
  NodeId,
  PortDescriptor,
  PortId,
} from "./types";

export interface ConnectionCheckContext {
  nodes: GraphNode[];
  edges: GraphEdge[];
  descriptors: BlockDescriptor[];

  from: GraphPortEndpoint;
  to: GraphPortEndpoint;
}

export function canConnect(context: ConnectionCheckContext): ConnectionCheckResult {
  const { nodes, edges, descriptors, from, to } = context;

  if (from.nodeId === to.nodeId) {
    return {
      ok: false,
      reason: "A block cannot be connected to itself.",
      code: "self_connection",
    };
  }

  const fromNode = findNode(nodes, from.nodeId);
  const toNode = findNode(nodes, to.nodeId);

  if (!fromNode) {
    return {
      ok: false,
      reason: `Source node not found: ${from.nodeId}`,
      code: "source_node_not_found",
    };
  }

  if (!toNode) {
    return {
      ok: false,
      reason: `Target node not found: ${to.nodeId}`,
      code: "target_node_not_found",
    };
  }

  const fromDescriptor = findBlockDescriptor(descriptors, fromNode.type);
  const toDescriptor = findBlockDescriptor(descriptors, toNode.type);

  if (!fromDescriptor) {
    return {
      ok: false,
      reason: `Unknown source block type: ${fromNode.type}`,
      code: "source_descriptor_not_found",
    };
  }

  if (!toDescriptor) {
    return {
      ok: false,
      reason: `Unknown target block type: ${toNode.type}`,
      code: "target_descriptor_not_found",
    };
  }

  const fromPort = findOutputPort(fromDescriptor, from.portId);
  const toPort = findInputPort(toDescriptor, to.portId);

  if (!fromPort) {
    return {
      ok: false,
      reason: `Source output port not found: ${fromNode.title}.${from.portId}`,
      code: "source_output_port_not_found",
    };
  }

  if (!toPort) {
    return {
      ok: false,
      reason: `Target input port not found: ${toNode.title}.${to.portId}`,
      code: "target_input_port_not_found",
    };
  }

  if (!toPort.accepts || !toPort.accepts.includes(fromPort.kind)) {
    return {
      ok: false,
      reason: `${toNode.title}.${toPort.label} does not accept ${fromPort.kind}.`,
      code: "port_kind_mismatch",
    };
  }

  if (isDuplicateConnection(edges, from, to)) {
    return {
      ok: false,
      reason: "This connection already exists.",
      code: "duplicate_connection",
    };
  }

  if (isInputPortAtCapacity(edges, toPort, to)) {
    return {
      ok: false,
      reason: `${toNode.title}.${toPort.label} has reached its connection limit.`,
      code: "max_connections_reached",
    };
  }

  return {
    ok: true,
  };
}

export function findNode(nodes: GraphNode[], nodeId: NodeId): GraphNode | undefined {
  return nodes.find((node) => node.id === nodeId);
}

export function findBlockDescriptor(
  descriptors: BlockDescriptor[],
  type: string,
): BlockDescriptor | undefined {
  return descriptors.find((descriptor) => descriptor.type === type);
}

export function findInputPort(
  descriptor: BlockDescriptor,
  portId: PortId,
): PortDescriptor | undefined {
  return descriptor.inputs.find((port) => port.id === portId);
}

export function findOutputPort(
  descriptor: BlockDescriptor,
  portId: PortId,
): PortDescriptor | undefined {
  return descriptor.outputs.find((port) => port.id === portId);
}

export function isDuplicateConnection(
  edges: GraphEdge[],
  from: GraphPortEndpoint,
  to: GraphPortEndpoint,
): boolean {
  return edges.some(
    (edge) =>
      edge.from.nodeId === from.nodeId &&
      edge.from.portId === from.portId &&
      edge.to.nodeId === to.nodeId &&
      edge.to.portId === to.portId,
  );
}

export function countIncomingConnections(
  edges: GraphEdge[],
  endpoint: GraphPortEndpoint,
): number {
  return edges.filter(
    (edge) =>
      edge.to.nodeId === endpoint.nodeId &&
      edge.to.portId === endpoint.portId,
  ).length;
}

export function isInputPortAtCapacity(
  edges: GraphEdge[],
  inputPort: PortDescriptor,
  endpoint: GraphPortEndpoint,
): boolean {
  const maxConnections = inputPort.maxConnections;

  if (maxConnections === undefined || maxConnections === "unlimited") {
    return false;
  }

  const incomingCount = countIncomingConnections(edges, endpoint);

  return incomingCount >= maxConnections;
}

export function getCompatibleInputEndpoints(
  params: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    descriptors: BlockDescriptor[];
    from: GraphPortEndpoint;
  },
): GraphPortEndpoint[] {
  const { nodes, edges, descriptors, from } = params;
  const result: GraphPortEndpoint[] = [];

  for (const node of nodes) {
    const descriptor = findBlockDescriptor(descriptors, node.type);

    if (!descriptor) {
      continue;
    }

    for (const inputPort of descriptor.inputs) {
      const to: GraphPortEndpoint = {
        nodeId: node.id,
        portId: inputPort.id,
      };

      const check = canConnect({
        nodes,
        edges,
        descriptors,
        from,
        to,
      });

      if (check.ok) {
        result.push(to);
      }
    }
  }

  return result;
}