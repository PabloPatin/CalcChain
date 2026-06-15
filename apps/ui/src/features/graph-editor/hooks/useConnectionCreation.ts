import { useCallback, useMemo, useState } from "react";

import type {
  BlockDescriptor,
  ConnectionCheckResult,
  GraphEdge,
  GraphNode,
  GraphPortEndpoint,
  NodeId,
  PortId,
} from "../model/types";
import type { ConnectionRule } from "../../../shared/api/backendTypes";

import {
  canConnect,
  getCompatibleInputEndpoints,
} from "../model/connectionRules";

export interface PendingConnection {
  from: GraphPortEndpoint;
}

export interface UseConnectionCreationParams {
  nodes: GraphNode[];

  edges: GraphEdge[];
  descriptors: BlockDescriptor[];
  connectionRules?: ConnectionRule[];

  onCreateEdge: (
    from: GraphPortEndpoint,
    to: GraphPortEndpoint,
  ) => GraphEdge | null;
}

export interface UseConnectionCreationResult {
  pendingConnection: PendingConnection | null;

  compatibleInputEndpoints: GraphPortEndpoint[];

  startConnection: (from: GraphPortEndpoint) => void;
  completeConnection: (to: GraphPortEndpoint) => ConnectionCheckResult;
  cancelConnection: () => void;

  isCreatingConnection: boolean;
  isCompatibleInput: (nodeId: NodeId, portId: PortId) => boolean;
}

/**
 * Handles interactive connection creation:
 *
 * output port click
 *   -> pending connection
 *   -> compatible input ports are highlighted
 *   -> input port click
 *   -> validate connection
 *   -> create edge
 */
export function useConnectionCreation({
  nodes,
  edges,
  descriptors,
  connectionRules = [],
  onCreateEdge,
}: UseConnectionCreationParams): UseConnectionCreationResult {
  const [pendingConnection, setPendingConnection] =
    useState<PendingConnection | null>(null);

  const startConnection = useCallback((from: GraphPortEndpoint) => {
    setPendingConnection({
      from,
    });
  }, []);

  const cancelConnection = useCallback(() => {
    setPendingConnection(null);
  }, []);

  const completeConnection = useCallback(
    (to: GraphPortEndpoint): ConnectionCheckResult => {
      if (!pendingConnection) {
        return {
          ok: false,
          reason: "Нет начатого соединения.",
          code: "no_pending_connection",
        };
      }

      const check = canConnect({
        nodes,
        edges,
        descriptors,
        connectionRules,
        from: pendingConnection.from,
        to,
      });

      if (!check.ok) {
        return check;
      }

      onCreateEdge(pendingConnection.from, to);
      setPendingConnection(null);

      return {
        ok: true,
      };
    },
    [pendingConnection, nodes, edges, descriptors, connectionRules, onCreateEdge],
  );

  const compatibleInputEndpoints = useMemo(() => {
    if (!pendingConnection) {
      return [];
    }

    return getCompatibleInputEndpoints({
      nodes,
      edges,
      descriptors,
      connectionRules,
      from: pendingConnection.from,
    });
  }, [pendingConnection, nodes, edges, descriptors, connectionRules]);

  const isCompatibleInput = useCallback(
    (nodeId: NodeId, portId: PortId): boolean => {
      return compatibleInputEndpoints.some(
        (endpoint) =>
          endpoint.node_id === nodeId && endpoint.port_id === portId,
      );
    },
    [compatibleInputEndpoints],
  );

  return {
    pendingConnection,
    compatibleInputEndpoints,

    startConnection,
    completeConnection,
    cancelConnection,

    isCreatingConnection: pendingConnection !== null,
    isCompatibleInput,
  };
}
