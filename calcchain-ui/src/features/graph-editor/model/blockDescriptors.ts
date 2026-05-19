import type { BlockDescriptor, BlockType } from "./types";
import { PORT_KIND } from "./portKinds";

export const BLOCK_TYPE = {
  CALCULATION: "calculation",
  RULE_SET: "rule-set",
  ENV: "env",

  OUTPUT_ARTIFACT: "output-artifact",

  LOCAL_INPUT: "local-input",
  LOCAL_CODE_INPUT: "local-code-input",
  LOCAL_OUTPUT: "local-output",
} as const satisfies Record<string, BlockType>;

/**
 * Minimal fallback block descriptors.
 *
 * Main production source should be backend:
 * GET /api/capabilities/blocks
 *
 * These descriptors are used only when backend is unavailable
 * or during early local development.
 */
export const FALLBACK_BLOCK_DESCRIPTORS: BlockDescriptor[] = [
  {
    type: BLOCK_TYPE.CALCULATION,
    title: "Calculation",
    category: "Processing",
    description: "Runs a calculation command using prepared code, inputs and environment.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "calculation",
      id: "process",
    },
    inputs: [
      {
        id: "code",
        label: "code",
        kind: PORT_KIND.CODE,
        accepts: [PORT_KIND.CODE],
        maxConnections: 1,
        required: true,
        description: "Calculation code source.",
      },
      {
        id: "input",
        label: "input",
        kind: PORT_KIND.INPUT,
        accepts: [PORT_KIND.INPUT, PORT_KIND.MAPPED, PORT_KIND.ARTIFACT],
        maxConnections: "unlimited",
        description: "Calculation input files or upstream artifacts.",
      },
      {
        id: "env",
        label: "env",
        kind: PORT_KIND.ENV,
        accepts: [PORT_KIND.ENV],
        maxConnections: "unlimited",
        description: "Runtime environment variables.",
      },
    ],
    outputs: [
      {
        id: "output",
        label: "output",
        kind: PORT_KIND.OUTPUT,
        description: "Files produced by the calculation.",
      },
    ],
    defaultData: {
      executable: "",
      args: [],
      cwd: "work",
      timeoutSec: 3600,
    },
    defaultSize: {
      width: 286,
    },
  },

  {
    type: BLOCK_TYPE.RULE_SET,
    title: "Rule Set",
    category: "Mapping",
    description: "Applies mapping/classification rules to inputs or outputs.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "rule",
      id: "rule-set",
    },
    inputs: [
      {
        id: "source",
        label: "input/output",
        kind: "ruleable",
        accepts: [PORT_KIND.INPUT, PORT_KIND.OUTPUT, PORT_KIND.ARTIFACT],
        maxConnections: 1,
        required: true,
        description: "Files or artifacts to which this rule set is applied.",
      },
    ],
    outputs: [
      {
        id: "mapped",
        label: "mapped",
        kind: PORT_KIND.MAPPED,
        description: "Files after applying the selected rule_set.",
      },
    ],
    defaultData: {
      ruleSet: "",
      rulesFile: "",
    },
  },

  {
    type: BLOCK_TYPE.ENV,
    title: "Env",
    category: "Context",
    description: "Environment variables for calculation runtime.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "env",
      id: "variables",
    },
    inputs: [],
    outputs: [
      {
        id: "env",
        label: "env",
        kind: PORT_KIND.ENV,
        description: "Runtime environment.",
      },
    ],
    defaultData: {
      variables: {},
      secretVariables: [],
    },
  },

  {
    type: BLOCK_TYPE.OUTPUT_ARTIFACT,
    title: "Output Artifact",
    category: "Outputs",
    description: "Named artifact produced by a calculation.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "target",
      id: "artifact",
    },
    inputs: [
      {
        id: "output",
        label: "output",
        kind: PORT_KIND.OUTPUT,
        accepts: [PORT_KIND.OUTPUT, PORT_KIND.MAPPED],
        maxConnections: "unlimited",
        required: true,
        description: "Calculation output or mapped output.",
      },
    ],
    outputs: [
      {
        id: "artifact",
        label: "artifact",
        kind: PORT_KIND.ARTIFACT,
        description: "Artifact for publication or for the next calculation.",
      },
    ],
    defaultData: {
      group: "outputs",
      pathPattern: "results/**",
    },
  },

  {
    type: BLOCK_TYPE.LOCAL_INPUT,
    title: "Local Input",
    category: "Sources",
    description: "Input files from a local folder.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "source",
      id: "local",
    },
    inputs: [],
    outputs: [
      {
        id: "files",
        label: "files",
        kind: PORT_KIND.INPUT,
        description: "Input files from a local source.",
      },
    ],
    defaultData: {
      sourceType: "local",
      role: "input",
      path: "",
    },
  },

  {
    type: BLOCK_TYPE.LOCAL_CODE_INPUT,
    title: "Local Code Input",
    category: "Sources",
    description: "Calculation code from a local folder.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "source",
      id: "local",
    },
    inputs: [],
    outputs: [
      {
        id: "code",
        label: "code",
        kind: PORT_KIND.CODE,
        description: "Calculation code files.",
      },
    ],
    defaultData: {
      sourceType: "local",
      role: "code",
      path: "",
    },
  },

  {
    type: BLOCK_TYPE.LOCAL_OUTPUT,
    title: "Local Output",
    category: "Outputs",
    description: "Publish outputs or artifacts to a local folder.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "target",
      id: "local",
    },
    inputs: [
      {
        id: "publish",
        label: "publish",
        kind: PORT_KIND.OUTPUT,
        accepts: [PORT_KIND.OUTPUT, PORT_KIND.ARTIFACT, PORT_KIND.MAPPED],
        maxConnections: "unlimited",
        required: true,
        description: "Outputs or artifacts to publish.",
      },
    ],
    outputs: [],
    defaultData: {
      targetType: "local",
      path: "",
    },
  },
];

/**
 * Creates fast lookup map by block type.
 */
export function createBlockDescriptorMap(
  descriptors: BlockDescriptor[],
): Map<BlockType, BlockDescriptor> {
  return new Map(descriptors.map((descriptor) => [descriptor.type, descriptor]));
}

/**
 * Production behavior:
 *
 * - if backend returned descriptors, use them;
 * - if backend is unavailable or returned empty list, use fallback descriptors.
 */
export function resolveBlockDescriptors(
  backendDescriptors: BlockDescriptor[] | null | undefined,
): BlockDescriptor[] {
  if (backendDescriptors && backendDescriptors.length > 0) {
    return backendDescriptors;
  }

  return FALLBACK_BLOCK_DESCRIPTORS;
}

/**
 * Optional helper if we want backend descriptors to be primary,
 * but still fill missing fallback core blocks.
 *
 * This is useful during backend development.
 */
export function mergeWithFallbackBlockDescriptors(
  backendDescriptors: BlockDescriptor[] | null | undefined,
): BlockDescriptor[] {
  const result = createBlockDescriptorMap(FALLBACK_BLOCK_DESCRIPTORS);

  for (const descriptor of backendDescriptors ?? []) {
    result.set(descriptor.type, descriptor);
  }

  return Array.from(result.values());
}

export function getBlockDescriptor(
  descriptors: BlockDescriptor[],
  type: BlockType,
): BlockDescriptor | undefined {
  return descriptors.find((descriptor) => descriptor.type === type);
}

export function requireBlockDescriptor(
  descriptors: BlockDescriptor[],
  type: BlockType,
): BlockDescriptor {
  const descriptor = getBlockDescriptor(descriptors, type);

  if (!descriptor) {
    throw new Error(`Unknown block type: ${type}`);
  }

  return descriptor;
}

export function groupBlockDescriptorsByCategory(
  descriptors: BlockDescriptor[],
): Record<string, BlockDescriptor[]> {
  return descriptors.reduce<Record<string, BlockDescriptor[]>>(
    (groups, descriptor) => {
      groups[descriptor.category] ??= [];
      groups[descriptor.category].push(descriptor);
      return groups;
    },
    {},
  );
}