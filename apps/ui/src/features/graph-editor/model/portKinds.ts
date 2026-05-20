import type { PortKind } from "./types";

/**
 * Built-in CalcChain port kinds.
 *
 * Keep these constants instead of writing raw strings like "input" or "auth"
 * across the app. This reduces typo risk.
 */
export const PORT_KIND = {
  AUTH: "auth",
  INPUT: "input",
  CODE: "code",
  ENV: "env",
  OUTPUT: "output",
  ARTIFACT: "artifact",
  MAPPED: "mapped",
} as const satisfies Record<string, PortKind>;

/**
 * Union type of built-in port kinds.
 *
 * Equivalent to:
 * "auth" | "input" | "code" | "env" | "output" | "artifact" | "mapped"
 */
export type BuiltInPortKind = (typeof PORT_KIND)[keyof typeof PORT_KIND];

/**
 * List of built-in port kinds.
 * Useful for validation, selects, debug panels, etc.
 */
export const BUILT_IN_PORT_KINDS = Object.values(PORT_KIND) as BuiltInPortKind[];

/**
 * Human-readable labels for built-in port kinds.
 */
export const PORT_KIND_LABELS: Record<BuiltInPortKind, string> = {
  [PORT_KIND.AUTH]: "Auth",
  [PORT_KIND.INPUT]: "Input",
  [PORT_KIND.CODE]: "Code",
  [PORT_KIND.ENV]: "Environment",
  [PORT_KIND.OUTPUT]: "Output",
  [PORT_KIND.ARTIFACT]: "Artifact",
  [PORT_KIND.MAPPED]: "Mapped",
};

/**
 * Checks whether a port kind is one of CalcChain built-in kinds.
 *
 * Plugin-defined port kinds are allowed by the PortKind type,
 * but this function helps distinguish built-in kinds from external ones.
 */
export function isBuiltInPortKind(kind: PortKind): kind is BuiltInPortKind {
  return (BUILT_IN_PORT_KINDS as readonly string[]).includes(kind);
}

/**
 * Returns a readable label for a port kind.
 *
 * Built-in kinds get nice labels.
 * Plugin-defined kinds are returned as-is.
 */
export function getPortKindLabel(kind: PortKind): string {
  if (isBuiltInPortKind(kind)) {
    return PORT_KIND_LABELS[kind];
  }

  return kind;
}