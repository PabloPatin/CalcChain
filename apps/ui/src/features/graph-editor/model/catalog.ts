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
    title: localizedBlockTitle(block),
    category: localizedCategory(block.category) as BlockCategory,
    description: localizedBlockDescription(block),
    inputs,
    outputs,
    defaultData: getDefaultData(block.config_schema),
    configSchema: localizedConfigSchema(block.config_schema),
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
    label: localizedPortTitle(port),
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

function localizedBlockTitle(block: BackendBlockDescriptor): string {
  return BLOCK_TITLE_BY_TYPE[block.type] ?? block.title;
}

function localizedBlockDescription(block: BackendBlockDescriptor): string | undefined {
  return BLOCK_DESCRIPTION_BY_TYPE[block.type] ?? block.description ?? undefined;
}

function localizedCategory(category: string): string {
  return CATEGORY_BY_VALUE[category] ?? category;
}

function localizedPortTitle(port: BackendPortDescriptor): string {
  return PORT_TITLE_BY_ID[port.id] ?? PORT_TITLE_BY_KIND[port.kind] ?? port.title;
}

function getDefaultValue(schema: JsonObject): JsonValue {
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

function localizedConfigSchema(schema: JsonObject): JsonObject {
  const properties = getObjectProperty(schema, "properties");
  if (!properties) {
    return schema;
  }

  const nextProperties: JsonObject = {};
  for (const [key, rawProperty] of Object.entries(properties)) {
    if (!isJsonObject(rawProperty)) {
      nextProperties[key] = rawProperty;
      continue;
    }
    const rawTitle = rawProperty.title;
    const title = typeof rawTitle === "string"
      ? CONFIG_TITLE_BY_VALUE[rawTitle] ?? CONFIG_TITLE_BY_KEY[key] ?? rawTitle
      : CONFIG_TITLE_BY_KEY[key];
    nextProperties[key] = title ? { ...rawProperty, title } : rawProperty;
  }

  return {
    ...schema,
    properties: nextProperties,
  };
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

const BLOCK_TITLE_BY_TYPE: Record<string, string> = {
  "source.local.input": "Локальный источник данных",
  "source.local.code": "Локальный источник кода",
  "source.svn.input": "SVN-источник данных",
  "source.svn.code": "SVN-источник кода",
  "rule-set": "Набор правил",
  calculation: "Расчёт",
  "env.public": "Переменная окружения",
  "env.secret": "Секретная переменная окружения",
  "artifact.output": "Выходной артефакт",
  "target.local": "Локальная папка результата",
  "target.svn": "SVN-папка результата",
  "auth.login-password": "Логин и пароль",
};

const BLOCK_DESCRIPTION_BY_TYPE: Record<string, string> = {
  "source.local.input": "Входные данные из локальной папки или файла.",
  "source.local.code": "Код расчёта из локальной папки.",
  "source.svn.input": "Входные данные из SVN.",
  "source.svn.code": "Код расчёта из SVN.",
  "rule-set": "Правила сопоставления файлов.",
  calculation: "Команда запуска расчёта.",
  "env.public": "Обычная переменная окружения для запуска.",
  "env.secret": "Секретная переменная окружения из хранилища сессии.",
  "artifact.output": "Описание результата, созданного расчётом.",
  "target.local": "Публикация результата в локальную папку.",
  "target.svn": "Публикация результата в SVN.",
  "auth.login-password": "Учётные данные для источников и целей.",
};

const CATEGORY_BY_VALUE: Record<string, string> = {
  Input: "Источники",
  Code: "Код",
  Transform: "Правила",
  Run: "Расчёт",
  Environment: "Окружение",
  Output: "Результаты",
  Target: "Назначения",
  Auth: "Доступ",
  Sources: "Источники",
  Mapping: "Правила",
  Processing: "Расчёт",
  Context: "Окружение",
  Outputs: "Результаты",
};

const PORT_TITLE_BY_ID: Record<string, string> = {
  auth: "Доступ",
  output: "Выход",
  input: "Данные",
  code: "Код",
  env: "Окружение",
  source: "Источник",
  mapped: "После правил",
  artifact: "Артефакт",
};

const PORT_TITLE_BY_KIND: Record<string, string> = {
  auth: "Доступ",
  input: "Данные",
  "calculation.input": "Данные расчёта",
  code: "Код",
  "calculation.code": "Код расчёта",
  env: "Окружение",
  "calculation.env": "Окружение расчёта",
  "calculation.output": "Результат расчёта",
  artifact: "Артефакт",
  target: "Назначение",
  mapped: "После правил",
};

const CONFIG_TITLE_BY_VALUE: Record<string, string> = {
  Path: "Путь",
  Command: "Команда",
  "Working directory": "Рабочая папка",
  "Stdin mode": "Режим stdin",
  "Stdin text": "Текст stdin",
  Encoding: "Кодировка",
  "Timeout seconds": "Тайм-аут, сек",
  Name: "Имя",
  Value: "Значение",
  Username: "Логин",
  Password: "Пароль",
  "Credential reference": "Ссылка на секрет",
  "SVN URL": "URL SVN",
  Revision: "Ревизия",
};

const CONFIG_TITLE_BY_KEY: Record<string, string> = {
  path: "Путь",
  command: "Команда",
  working_directory: "Рабочая папка",
  cwd: "Рабочая папка",
  stdin_mode: "Режим stdin",
  stdin_text: "Текст stdin",
  encoding: "Кодировка",
  timeout_seconds: "Тайм-аут, сек",
  name: "Имя",
  value: "Значение",
  username: "Логин",
  password: "Пароль",
  credential_ref: "Ссылка на секрет",
  location: "Адрес",
  revision: "Ревизия",
  rules: "Правила",
  rule_set: "Набор правил",
  rule_sets: "Наборы правил",
};

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
