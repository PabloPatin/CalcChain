import type { BlockDescriptor, BlockType } from "./types";
import { PORT_KIND } from "./portKinds";

export const BLOCK_TYPE = {
  CALCULATION: "calculation",
  RULE_SET: "rule-set",
  ENV_PUBLIC: "env.public",
  ENV_SECRET: "env.secret",

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
      command: "",
      working_directory: ".",
      stdin_mode: "none",
      stdin_text: "",
      encoding: "utf-8",
      timeout_seconds: null,
    },
    configSchema: {
      type: "object",
      properties: {
        command: { type: "string", title: "Command" },
        working_directory: { type: "string", title: "Working directory" },
        stdin_mode: {
          type: "string",
          title: "Stdin mode",
          enum: ["none", "script"],
          default: "none",
        },
        stdin_text: {
          type: "string",
          title: "Stdin text",
          default: "",
          format: "textarea",
        },
        encoding: { type: "string", title: "Encoding", default: "utf-8" },
        timeout_seconds: {
          type: ["integer", "null"],
          title: "Timeout seconds",
          default: null,
        },
      },
      required: ["command"],
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
    type: BLOCK_TYPE.ENV_PUBLIC,
    title: "Public Env",
    category: "Environment",
    description: "Plain runtime environment variable.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "env",
      id: "public",
    },
    inputs: [],
    outputs: [
      {
        id: "output",
        label: "env",
        kind: PORT_KIND.ENV,
        description: "Runtime environment.",
      },
    ],
    defaultData: {
      name: "",
      value: "",
    },
    configSchema: {
      type: "object",
      properties: {
        name: { type: "string", title: "Name" },
        value: { type: "string", title: "Value" },
      },
      required: ["name", "value"],
    },
  },

  {
    type: BLOCK_TYPE.ENV_SECRET,
    title: "Secret Env",
    category: "Environment",
    description: "Secret runtime environment variable stored in backend session secrets.",
    provider: {
      kind: "core",
    },
    capability: {
      namespace: "env",
      id: "secret",
    },
    inputs: [],
    outputs: [
      {
        id: "output",
        label: "env",
        kind: PORT_KIND.ENV,
        description: "Runtime environment.",
      },
    ],
    defaultData: {
      name: "",
      value: "",
    },
    configSchema: {
      type: "object",
      properties: {
        name: { type: "string", title: "Name" },
        value: {
          type: "string",
          title: "Value",
          format: "password",
          writeOnly: true,
          "x-calcchain-credential": "secret",
          "x-calcchain-secret": true,
        },
      },
      required: ["name", "value"],
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
    return backendDescriptors.map(localizeDescriptor);
  }

  return FALLBACK_BLOCK_DESCRIPTORS.map(localizeDescriptor);
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
    result.set(descriptor.type, localizeDescriptor(descriptor));
  }

  return Array.from(result.values()).map(localizeDescriptor);
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
    throw new Error(`Неизвестный тип блока: ${type}`);
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

function localizeDescriptor(descriptor: BlockDescriptor): BlockDescriptor {
  return {
    ...descriptor,
    title: BLOCK_TITLE_BY_TYPE[descriptor.type] ?? descriptor.title,
    category: (CATEGORY_BY_VALUE[descriptor.category] ?? descriptor.category) as BlockDescriptor["category"],
    description: BLOCK_DESCRIPTION_BY_TYPE[descriptor.type] ?? descriptor.description,
    inputs: descriptor.inputs.map(localizePort),
    outputs: descriptor.outputs.map(localizePort),
    configSchema: localizeConfigSchema(descriptor.configSchema),
  };
}

function localizePort(port: BlockDescriptor["inputs"][number]): BlockDescriptor["inputs"][number] {
  return {
    ...port,
    label: PORT_LABEL_BY_ID[port.id] ?? PORT_LABEL_BY_KIND[port.kind] ?? port.label,
    description: port.description ? PORT_DESCRIPTION_BY_ID[port.id] ?? port.description : port.description,
  };
}

function localizeConfigSchema(schema: BlockDescriptor["configSchema"]): BlockDescriptor["configSchema"] {
  const properties = schema?.properties;
  if (typeof properties !== "object" || properties === null || Array.isArray(properties)) {
    return schema;
  }

  const nextProperties: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(properties)) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      nextProperties[key] = value;
      continue;
    }
    const property = value as Record<string, unknown>;
    const rawTitle = property.title;
    const title = typeof rawTitle === "string"
      ? CONFIG_TITLE_BY_VALUE[rawTitle] ?? CONFIG_TITLE_BY_KEY[key] ?? rawTitle
      : CONFIG_TITLE_BY_KEY[key];
    nextProperties[key] = title ? { ...property, title } : property;
  }

  return {
    ...schema,
    properties: nextProperties,
  };
}

const BLOCK_TITLE_BY_TYPE: Record<string, string> = {
  calculation: "Расчёт",
  "rule-set": "Набор правил",
  "env.public": "Переменная окружения",
  "env.secret": "Секретная переменная окружения",
  "artifact.output": "Выходной артефакт",
  "output-artifact": "Выходной артефакт",
  "source.local.input": "Локальный источник данных",
  "source.local.code": "Локальный источник кода",
  "source.svn.input": "SVN-источник данных",
  "source.svn.code": "SVN-источник кода",
  "target.local": "Локальная папка результата",
  "target.svn": "SVN-папка результата",
  "auth.login-password": "Логин и пароль",
  "local-input": "Локальный источник данных",
  "local-code-input": "Локальный источник кода",
  "local-output": "Локальная папка результата",
};

const BLOCK_DESCRIPTION_BY_TYPE: Record<string, string> = {
  calculation: "Запускает команду расчёта с подготовленным кодом, данными и окружением.",
  "rule-set": "Применяет правила сопоставления к файлам.",
  "env.public": "Обычная переменная окружения для запуска.",
  "env.secret": "Секретная переменная окружения из хранилища сессии.",
  "artifact.output": "Именованный артефакт, созданный расчётом.",
  "output-artifact": "Именованный артефакт, созданный расчётом.",
  "source.local.input": "Входные файлы из локальной папки.",
  "source.local.code": "Код расчёта из локальной папки.",
  "source.svn.input": "Входные данные из SVN.",
  "source.svn.code": "Код расчёта из SVN.",
  "target.local": "Публикация результатов в локальную папку.",
  "target.svn": "Публикация результатов в SVN.",
  "auth.login-password": "Учётные данные для источников и папок результата.",
  "local-input": "Входные файлы из локальной папки.",
  "local-code-input": "Код расчёта из локальной папки.",
  "local-output": "Публикация результатов в локальную папку.",
};

const CATEGORY_BY_VALUE: Record<string, string> = {
  Input: "Источники",
  Code: "Код",
  Sources: "Источники",
  Transform: "Правила",
  Mapping: "Правила",
  Run: "Расчёт",
  Processing: "Расчёт",
  Environment: "Окружение",
  Context: "Окружение",
  Output: "Результаты",
  Outputs: "Результаты",
  Target: "Назначения",
  Auth: "Доступ",
};

const PORT_LABEL_BY_ID: Record<string, string> = {
  auth: "Доступ",
  output: "Выход",
  input: "Данные",
  code: "Код",
  env: "Окружение",
  source: "Источник",
  mapped: "После правил",
  artifact: "Артефакт",
  files: "Файлы",
  publish: "Публикация",
};

const PORT_LABEL_BY_KIND: Record<string, string> = {
  auth: "Доступ",
  input: "Данные",
  code: "Код",
  env: "Окружение",
  output: "Результат",
  artifact: "Артефакт",
  mapped: "После правил",
  target: "Назначение",
  "calculation.input": "Данные расчёта",
  "calculation.code": "Код расчёта",
  "calculation.env": "Окружение расчёта",
  "calculation.output": "Результат расчёта",
};

const PORT_DESCRIPTION_BY_ID: Record<string, string> = {
  auth: "Данные доступа.",
  output: "Выход блока.",
  input: "Входные данные.",
  code: "Код расчёта.",
  env: "Окружение запуска.",
  source: "Источник файлов.",
  mapped: "Файлы после применения правил.",
  artifact: "Артефакт для публикации или следующего расчёта.",
};

const CONFIG_TITLE_BY_VALUE: Record<string, string> = {
  Command: "Команда",
  "Working directory": "Рабочая папка",
  "Stdin mode": "Режим stdin",
  "Stdin text": "Текст stdin",
  Encoding: "Кодировка",
  "Timeout seconds": "Тайм-аут, сек",
  Path: "Путь",
  Name: "Имя",
  Value: "Значение",
  Username: "Логин",
  Password: "Пароль",
  "Credential reference": "Ссылка на секрет",
  "SVN URL": "URL SVN",
  Revision: "Ревизия",
};

const CONFIG_TITLE_BY_KEY: Record<string, string> = {
  command: "Команда",
  working_directory: "Рабочая папка",
  cwd: "Рабочая папка",
  stdin_mode: "Режим stdin",
  stdin_text: "Текст stdin",
  encoding: "Кодировка",
  timeout_seconds: "Тайм-аут, сек",
  path: "Путь",
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
