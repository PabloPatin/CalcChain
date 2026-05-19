// В этом файлое представлены только логические компоненты ui

/**
 * Stable primitive identifiers.
 */
export type NodeId = string;
export type EdgeId = string;
export type PortId = string;
export type BlockType = string;

/**
 * Port direction inside a block.
 */
export type PortDirection = "input" | "output";

/**
 * PortKind describes what kind of data/context can flow through a port.
 *
 * The `(string & {})` part keeps the type extensible for future plugin-defined
 * port kinds without losing autocomplete for built-in kinds.
 */
export type PortKind =
  | "auth"
  | "input"
  | "code"
  | "env"
  | "output"
  | "artifact"
  | "mapped"
  | (string & {});

/**
 * High-level block category for palette grouping.
 */
export type BlockCategory =
  | "Sources"
  | "Mapping"
  | "Processing"
  | "Context"
  | "Outputs"
  | (string & {});

/**
 * Canvas position in pixels.
 */
export interface CanvasPosition {
  x: number;
  y: number;
}

/**
 * Size in pixels.
 * Usually calculated by UI, but can be fixed for some blocks.
 */
export interface CanvasSize {
  width: number;
  height: number;
}

/**
 * Runtime/display status of a graph node.
 * This is UI-level status, not CalcChain manifest status.
 */
export type GraphNodeStatus =
  | "draft"
  | "configured"
  | "valid"
  | "invalid"
  | "running"
  | "succeeded"
  | "failed"
  | "unknown";

/**
 * Generic block data.
 *
 * Different block types will store different fields here:
 * - source blocks: path/location/revision/etc.
 * - calculation blocks: command/args/timeout/etc.
 * - env blocks: variables/secret names.
 * - auth blocks: provider/scheme/scope.
 *
 * Later we can replace this with stricter discriminated union types,
 * but this shape is convenient while plugin-defined blocks are expected.
 */
export type BlockData = Record<string, unknown>;

/**
 * Describes a single input or output port on a block descriptor.
 */
export interface PortDescriptor {
  /**
   * Stable port id inside the block type.
   *
   * Examples:
   * - "auth"
   * - "files"
   * - "code"
   * - "input"
   * - "env"
   * - "output"
   * - "mapped"
   */
  id: PortId;

  /**
   * Human-readable label shown near the port.
   */
  label: string;

  /**
   * What this port produces or consumes.
   */
  kind: PortKind;

  /**
   * For input ports: which output port kinds are accepted.
   * For output ports: usually omitted.
   */
  accepts?: PortKind[];

  /**
   * Maximum incoming connections for this input port.
   *
   * Examples:
   * - SVN Source.auth: 1
   * - Calculation.code: 1
   * - Calculation.input: "unlimited"
   */
  maxConnections?: number | "unlimited";

  /**
   * Optional hint for tooltips or inspector.
   */
  description?: string;

  /**
   * Marks required input ports.
   * Used by graph validation.
   */
  required?: boolean;
}

/**
 * Describes a block type available in the palette.
 *
 * Later this can come from backend/plugin descriptors.
 */
export interface BlockDescriptor {
  /**
   * Stable block type.
   *
   * Examples:
   * - "local-input-source"
   * - "svn-input-source"
   * - "calculation"
   * - "rule-set"
   */
  type: BlockType;

  /**
   * Human-readable title.
   */
  title: string;

  /**
   * Palette category.
   */
  category: BlockCategory;

  /**
   * Short description shown in palette/inspector.
   */
  description?: string;

  /**
   * Input ports of this block.
   */
  inputs: PortDescriptor[];

  /**
   * Output ports of this block.
   */
  outputs: PortDescriptor[];

  /**
   * Initial data for a new node of this type.
   */
  defaultData: BlockData;

  /**
   * Optional fixed or preferred size.
   */
  defaultSize?: Partial<CanvasSize>;

  /**
   * Whether this block is provided by core or by a plugin.
   */
  provider?: BlockProvider;

  /**
   * Optional plugin/capability metadata.
   */
  capability?: CapabilityRef;
}

/**
 * Describes where a block/capability comes from.
 */
export interface BlockProvider {
  kind: "core" | "plugin";
  pluginId?: string;
  pluginVersion?: string;
}

/**
 * Reference to backend/plugin capability.
 *
 * Examples:
 * - source:local
 * - source:svn
 * - target:local
 * - target:svn
 * - auth:login-password
 */
export interface CapabilityRef {
  namespace: "source" | "target" | "auth" | "env" | "rule" | "calculation" | (string & {});
  id: string;
}

/**
 * A block instance placed on the canvas.
 */
export interface GraphNode {
  id: NodeId;

  /**
   * References BlockDescriptor.type.
   */
  type: BlockType;

  /**
   * User-visible title.
   * Can be customized per node.
   */
  title: string;

  /**
   * Position on canvas.
   */
  position: CanvasPosition;

  /**
   * Optional measured or fixed size.
   */
  size?: Partial<CanvasSize>;

  /**
   * Block-specific data.
   */
  data: BlockData;

  /**
   * UI/runtime status.
   */
  status?: GraphNodeStatus;

  /**
   * Optional warnings/errors attached to this node.
   */
  diagnostics?: GraphDiagnostic[];
}

/**
 * A concrete port endpoint on a concrete node.
 */
export interface GraphPortEndpoint {
  nodeId: NodeId;
  portId: PortId;
}

/**
 * Directed graph connection:
 *
 * source output port -> target input port
 */
export interface GraphEdge {
  id: EdgeId;

  from: GraphPortEndpoint;
  to: GraphPortEndpoint;

  /**
   * Optional edge data.
   *
   * We currently keep rule_set as a separate block,
   * but this field allows future edge-level metadata if needed.
   */
  data?: Record<string, unknown>;

  /**
   * Optional diagnostics attached to the connection.
   */
  diagnostics?: GraphDiagnostic[];
}

/**
 * Full graph document edited by the UI.
 */
export interface GraphDocument {
  schemaVersion: string;

  /**
   * Human-readable graph name.
   */
  name: string;

  nodes: GraphNode[];
  edges: GraphEdge[];

  /**
   * Optional viewport state.
   */
  viewport?: GraphViewport;

  /**
   * Optional graph-level metadata.
   */
  metadata?: Record<string, unknown>;
}

/**
 * Canvas viewport state.
 */
export interface GraphViewport {
  x: number;
  y: number;
  zoom: number;
}

/**
 * In-memory editor state.
 */
export interface GraphEditorState {
  document: GraphDocument;

  selectedNodeId: NodeId | null;
  selectedEdgeId: EdgeId | null;

  pendingConnection: PendingConnection | null;

  message?: string;
}

/**
 * Connection that is currently being created by the user.
 */
export interface PendingConnection {
  fromNodeId: NodeId;
  fromPortId: PortId;
}

/**
 * Coordinates of rendered ports.
 * Used by EdgeLayer to draw SVG lines from real DOM port points.
 */
export type PortPositionMap = Record<string, CanvasPosition>;

/**
 * Diagnostic severity.
 */
export type GraphDiagnosticLevel = "error" | "warning" | "info";

/**
 * Validation/diagnostic message.
 */
export interface GraphDiagnostic {
  level: GraphDiagnosticLevel;
  message: string;

  nodeId?: NodeId;
  edgeId?: EdgeId;
  portId?: PortId;

  code?: string;
}

/**
 * Result of checking whether a connection is allowed.
 */
export type ConnectionCheckResult =
  | {
      ok: true;
    }
  | {
      ok: false;
      reason: string;
      code?: string;
    };

/**
 * Result of graph validation.
 */
export interface GraphValidationResult {
  ok: boolean;
  diagnostics: GraphDiagnostic[];
}

/**
 * Data prepared for graph compiler/backend.
 */
export interface SerializedGraph {
  schemaVersion: string;
  name: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata?: Record<string, unknown>;
}