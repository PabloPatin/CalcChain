import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { RefObject } from "react";

import type {
  PortDirection,
  PortPositionMap,
} from "../model/types";

import { getElementCenterRelativeToCanvas } from "../utils/edgeGeometry";

export function createPortPositionKey(
  nodeId: string,
  direction: PortDirection,
  portId: string,
): string {
  return `${nodeId}:${direction}:${portId}`;
}

export interface UsePortPositionsParams {
  canvasRef: RefObject<HTMLElement | null>;
  scale?: number;

  /**
   * Values that should trigger recalculation.
   * Usually: [nodes, edges, selectedNodeId, selectedEdgeId]
   */
  dependencies?: unknown[];
}

export interface UsePortPositionsResult {
  portPositions: PortPositionMap;

  registerPort: (
    nodeId: string,
    direction: PortDirection,
    portId: string,
    element: HTMLElement | null,
  ) => void;

  measurePorts: () => void;
}

export function usePortPositions({
  canvasRef,
  scale = 1,
  dependencies = [],
}: UsePortPositionsParams): UsePortPositionsResult {
  const portElementsRef = useRef<Map<string, HTMLElement>>(new Map());
  const [portPositions, setPortPositions] = useState<PortPositionMap>({});

  const measurePorts = useCallback(() => {
    const canvasElement = canvasRef.current;

    if (!canvasElement) {
      setPortPositions((currentPositions) => {
        if (Object.keys(currentPositions).length === 0) {
          return currentPositions;
        }

        return {};
      });

      return;
    }

    const canvasRect = canvasElement.getBoundingClientRect();
    const nextPositions: PortPositionMap = {};

    for (const [key, element] of portElementsRef.current.entries()) {
      const elementRect = element.getBoundingClientRect();

      const position = getElementCenterRelativeToCanvas(
        canvasRect,
        elementRect,
      );
      nextPositions[key] = {
        x: position.x / scale,
        y: position.y / scale,
      };
    }

    setPortPositions((currentPositions) => {
      if (arePortPositionsEqual(currentPositions, nextPositions)) {
        return currentPositions;
      }

      return nextPositions;
    });
  }, [canvasRef, scale]);

  const registerPort = useCallback(
    (
      nodeId: string,
      direction: PortDirection,
      portId: string,
      element: HTMLElement | null,
    ) => {
      const key = createPortPositionKey(nodeId, direction, portId);

      if (element) {
        portElementsRef.current.set(key, element);
      } else {
        portElementsRef.current.delete(key);
      }

      /**
       * Important:
       * Do NOT call measurePorts() here.
       *
       * This function is used inside React ref callbacks.
       * Calling setState from a ref callback can cause an infinite render loop.
       */
    },
    [],
  );

  useLayoutEffect(() => {
    measurePorts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measurePorts, ...dependencies]);

  return {
    portPositions,
    registerPort,
    measurePorts,
  };
}

function arePortPositionsEqual(
  left: PortPositionMap,
  right: PortPositionMap,
): boolean {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);

  if (leftKeys.length !== rightKeys.length) {
    return false;
  }

  for (const key of leftKeys) {
    const leftPosition = left[key];
    const rightPosition = right[key];

    if (!rightPosition) {
      return false;
    }

    if (
      leftPosition.x !== rightPosition.x ||
      leftPosition.y !== rightPosition.y
    ) {
      return false;
    }
  }

  return true;
}
