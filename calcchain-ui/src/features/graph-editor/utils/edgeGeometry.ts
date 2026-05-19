import type { CanvasPosition } from "../model/types";

export interface EdgePathOptions {
  /**
   * Minimum horizontal distance for bezier control points.
   */
  minCurveOffset?: number;

  /**
   * How strongly the curve bends.
   * 0.5 means control points are placed at half of horizontal distance.
   */
  curveStrength?: number;
}

/**
 * Creates an SVG cubic bezier path between two canvas points.
 *
 * Python-аналогия:
 * это просто функция, которая принимает две точки
 * и возвращает строку для SVG path.
 */
export function createEdgePath(
  start: CanvasPosition,
  end: CanvasPosition,
  options: EdgePathOptions = {},
): string {
  const minCurveOffset = options.minCurveOffset ?? 80;
  const curveStrength = options.curveStrength ?? 0.45;

  const dx = end.x - start.x;
  const curveOffset = Math.max(minCurveOffset, Math.abs(dx) * curveStrength);

  return [
    `M ${start.x} ${start.y}`,
    `C ${start.x + curveOffset} ${start.y},`,
    `${end.x - curveOffset} ${end.y},`,
    `${end.x} ${end.y}`,
  ].join(" ");
}

/**
 * Creates a temporary edge path while the user is connecting ports.
 *
 * Same as createEdgePath, but named separately for readability in UI code.
 */
export function createPendingEdgePath(
  start: CanvasPosition,
  pointer: CanvasPosition,
): string {
  return createEdgePath(start, pointer, {
    minCurveOffset: 60,
    curveStrength: 0.35,
  });
}

/**
 * Returns the center point between two points.
 * Useful if later we want to draw labels on edges.
 */
export function getEdgeMidpoint(
  start: CanvasPosition,
  end: CanvasPosition,
): CanvasPosition {
  return {
    x: (start.x + end.x) / 2,
    y: (start.y + end.y) / 2,
  };
}

/**
 * Converts a DOMRect center into canvas coordinates.
 *
 * canvasRect — bounding rect of the whole canvas.
 * elementRect — bounding rect of a port DOM element.
 */
export function getElementCenterRelativeToCanvas(
  canvasRect: DOMRect,
  elementRect: DOMRect,
): CanvasPosition {
  return {
    x: elementRect.left - canvasRect.left + elementRect.width / 2,
    y: elementRect.top - canvasRect.top + elementRect.height / 2,
  };
}