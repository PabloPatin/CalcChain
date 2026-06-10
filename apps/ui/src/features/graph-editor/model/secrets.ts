import type { JsonObject } from "../../../shared/api/backendTypes";
import type { BlockDescriptor, GraphDocument, GraphNode } from "./types";

const SECRET_METADATA_KEYS = ["x-calcchain-secret", "x-secret", "secret"];

export function sanitizeGraphSecrets(
  graph: GraphDocument,
  descriptors: BlockDescriptor[],
): GraphDocument {
  const descriptorByType = new Map(
    descriptors.map((descriptor) => [descriptor.type, descriptor]),
  );

  return {
    ...graph,
    nodes: graph.nodes.map((node) =>
      sanitizeNodeSecrets(node, descriptorByType.get(node.type)),
    ),
  };
}

function sanitizeNodeSecrets(
  node: GraphNode,
  descriptor: BlockDescriptor | undefined,
): GraphNode {
  const secretFields = getSecretFieldNames(descriptor);
  if (secretFields.size === 0) {
    return node;
  }

  const config: JsonObject = { ...node.config };
  for (const fieldName of secretFields) {
    delete config[fieldName];
  }

  return {
    ...node,
    config,
  };
}

function getSecretFieldNames(descriptor: BlockDescriptor | undefined): Set<string> {
  const properties = getSchemaProperties(descriptor?.configSchema);
  if (properties === null) {
    return new Set();
  }

  const result = new Set<string>();
  for (const [fieldName, rawProperty] of Object.entries(properties)) {
    if (isSecretProperty(rawProperty)) {
      result.add(fieldName);
    }
  }
  return result;
}

function getSchemaProperties(schema: unknown): JsonObject | null {
  if (!isJsonObject(schema)) {
    return null;
  }

  const properties = schema.properties;
  return isJsonObject(properties) ? properties : null;
}

function isSecretProperty(value: unknown): boolean {
  if (!isJsonObject(value)) {
    return false;
  }

  if (value["x-calcchain-credential"] === "secret") {
    return true;
  }

  if (value.format === "password" || value.writeOnly === true) {
    return true;
  }

  return SECRET_METADATA_KEYS.some((key) => value[key] === true);
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
