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
import type { ConnectionRule } from "../../../shared/api/backendTypes";

export interface ConnectionCheckContext {
  nodes: GraphNode[];
  edges: GraphEdge[];
  descriptors: BlockDescriptor[];
  connectionRules?: ConnectionRule[];

  from: GraphPortEndpoint;
  to: GraphPortEndpoint;
}

export function canConnect(context: ConnectionCheckContext): ConnectionCheckResult {
  const { nodes, edges, descriptors, connectionRules = [], from, to } = context;

  if (from.node_id === to.node_id) {
    return {
      ok: false,
      reason: "Блок нельзя соединить с самим собой.",
      code: "self_connection",
    };
  }

  const fromNode = findNode(nodes, from.node_id);
  const toNode = findNode(nodes, to.node_id);

  if (!fromNode) {
    return {
      ok: false,
      reason: `Исходная нода не найдена: ${from.node_id}`,
      code: "source_node_not_found",
    };
  }

  if (!toNode) {
    return {
      ok: false,
      reason: `Целевая нода не найдена: ${to.node_id}`,
      code: "target_node_not_found",
    };
  }

  const fromDescriptor = findBlockDescriptor(descriptors, fromNode.type);
  const toDescriptor = findBlockDescriptor(descriptors, toNode.type);

  if (!fromDescriptor) {
    return {
      ok: false,
      reason: `Неизвестный тип исходного блока: ${fromNode.type}`,
      code: "source_descriptor_not_found",
    };
  }

  if (!toDescriptor) {
    return {
      ok: false,
      reason: `Неизвестный тип целевого блока: ${toNode.type}`,
      code: "target_descriptor_not_found",
    };
  }

  const fromPort = findOutputPort(fromDescriptor, from.port_id);
  const toPort = findInputPort(toDescriptor, to.port_id);

  if (!fromPort) {
    return {
      ok: false,
      reason: `Выходной порт не найден: ${fromNode.title}.${from.port_id}`,
      code: "source_output_port_not_found",
    };
  }

  if (!toPort) {
    return {
      ok: false,
      reason: `Входной порт не найден: ${toNode.title}.${to.port_id}`,
      code: "target_input_port_not_found",
    };
  }

  if (!isPortKindAccepted(fromPort, toPort, connectionRules)) {
    return {
      ok: false,
      reason: `${toNode.title}.${toPort.label} не принимает тип ${fromPort.kind}.`,
      code: "port_kind_mismatch",
    };
  }

  if (isDuplicateConnection(edges, from, to)) {
    return {
      ok: false,
      reason: "Такое соединение уже существует.",
      code: "duplicate_connection",
    };
  }

  if (isInputPortAtCapacity(edges, toPort, to)) {
    return {
      ok: false,
      reason: `${toNode.title}.${toPort.label} достиг лимита подключений.`,
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
      edge.source.node_id === from.node_id &&
      edge.source.port_id === from.port_id &&
      edge.target.node_id === to.node_id &&
      edge.target.port_id === to.port_id,
  );
}

export function countIncomingConnections(
  edges: GraphEdge[],
  endpoint: GraphPortEndpoint,
): number {
  return edges.filter(
    (edge) =>
      edge.target.node_id === endpoint.node_id &&
      edge.target.port_id === endpoint.port_id,
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

export function isPortKindAccepted(
  fromPort: PortDescriptor,
  toPort: PortDescriptor,
  connectionRules: ConnectionRule[],
): boolean {
  if (connectionRules.length > 0) {
    return connectionRules.some(
      (rule) => rule.from_kind === fromPort.kind && rule.to_kind === toPort.kind,
    );
  }

  return Boolean(toPort.accepts?.includes(fromPort.kind));
}

export function getCompatibleInputEndpoints(
  params: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    descriptors: BlockDescriptor[];
    connectionRules?: ConnectionRule[];
    from: GraphPortEndpoint;
  },
): GraphPortEndpoint[] {
  const { nodes, edges, descriptors, connectionRules = [], from } = params;
  const result: GraphPortEndpoint[] = [];

  for (const node of nodes) {
    const descriptor = findBlockDescriptor(descriptors, node.type);

    if (!descriptor) {
      continue;
    }

    for (const inputPort of descriptor.inputs) {
      const to: GraphPortEndpoint = {
        node_id: node.id,
        port_id: inputPort.id,
      };

      const check = canConnect({
        nodes,
        edges,
        descriptors,
        connectionRules,
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
