import type {
  BackendBlockDescriptor,
  BackendPortDescriptor,
  CatalogResponse,
  ConnectionRule,
  JsonObject,
  JsonValue,
} from "../../../shared/api/backendTypes";
import type {
  BlockCategory,
  BlockData,
  BlockDescriptor,
  BlockProvider,
  CapabilityRef,
  PortDescriptor,
  PortKind,
} from "./types";

export interface EditorCatalog {
  catalogVersion: string;
  descriptors: BlockDescriptor[];
  connectionRules: ConnectionRule[];
  plugins: string[];
}

export function mapCatalogResponse(catalog: CatalogResponse): EditorCatalog {
  return {
    catalogVersion: catalog.catalog_version,
    descriptors: catalog.blocks.map((block) => mapBlockDescriptor(block, catalog.connection_rules)),
    connectionRules: catalog.connection_rules,
    plugins: catalog.plugins,
  };
}

function mapBlockDescriptor(
  block: BackendBlockDescriptor,
  connectionRules: ConnectionRule[],
): BlockDescriptor {
  const inputs: PortDescriptor[] = [];
  const outputs: PortDescriptor[] = [];

  for (const port of block.ports) {
    const mappedPort = mapPortDescriptor(port, connectionRules);
    if (port.direction === "input") {
      inputs.push(mappedPort);
    } else {
      outputs.push(mappedPort);
    }
  }

  return {
    type: block.type,
    title: block.title,
    category: block.category as BlockCategory,
    description: block.description ?? undefined,
    inputs,
    outputs,
    defaultData: getDefaultData(block.config_schema),
    configSchema: block.config_schema,
    provider: getProvider(block),
    capability: getCapability(block),
  };
}

function mapPortDescriptor(
  port: BackendPortDescriptor,
  connectionRules: ConnectionRule[],
): PortDescriptor {
  const accepts = port.direction === "input"
    ? getAcceptedKinds(port.kind, connectionRules)
    : undefined;

  return {
    id: port.id,
    label: port.title,
    kind: port.kind as PortKind,
    accepts,
    maxConnections: port.max_connections ?? undefined,
    required: port.required,
  };
}

function getAcceptedKinds(
  toKind: string,
  connectionRules: ConnectionRule[],
): PortKind[] | undefined {
  const acceptedKinds = connectionRules
    .filter((rule) => rule.to_kind === toKind)
    .map((rule) => rule.from_kind as PortKind);

  return acceptedKinds.length > 0 ? acceptedKinds : undefined;
}

function getDefaultData(configSchema: JsonObject): BlockData {
  const properties = getObjectProperty(configSchema, "properties");
  if (!properties) {
    return {};
  }

  const data: BlockData = {};
  for (const [key, rawSchema] of Object.entries(properties)) {
    data[key] = isJsonObject(rawSchema) ? getDefaultValue(rawSchema) : "";
  }

  return data;
}

function getDefaultValue(schema: JsonObject): unknown {
  if ("default" in schema) {
    return schema.default;
  }

  const schemaType = schema.type;
  if (schemaType === "boolean") {
    return false;
  }
  if (schemaType === "integer" || schemaType === "number") {
    return 0;
  }
  if (schemaType === "array") {
    return [];
  }
  if (schemaType === "object") {
    return {};
  }

  return "";
}

function getProvider(block: BackendBlockDescriptor): BlockProvider {
  if (block.plugin_id) {
    return {
      kind: "plugin",
      pluginId: block.plugin_id,
    };
  }

  return {
    kind: "core",
  };
}

function getCapability(block: BackendBlockDescriptor): CapabilityRef | undefined {
  const [namespace, capabilityId] = block.type.split(".");
  if (!namespace || !capabilityId) {
    return undefined;
  }

  return {
    namespace: namespace as CapabilityRef["namespace"],
    id: capabilityId,
  };
}

function getObjectProperty(object: JsonObject, key: string): JsonObject | null {
  const value = object[key];
  return isJsonObject(value) ? value : null;
}

function isJsonObject(value: JsonValue | unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
