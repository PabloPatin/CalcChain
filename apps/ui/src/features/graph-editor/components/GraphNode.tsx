import type { MouseEvent } from "react";
import { Box, FileCode2, FileInput, FileOutput, Settings2, UploadCloud, Network } from "lucide-react";

import type {
  BlockDescriptor,
  GraphNode as GraphNodeModel,
  GraphPortEndpoint,
  NodeId,
  PortDirection,
  PortId,
} from "../model/types";

import { PortButton } from "./PortButton";

export interface GraphNodeProps {
  node: GraphNodeModel;
  descriptor: BlockDescriptor;
  selected: boolean;

  pendingConnectionFrom: GraphPortEndpoint | null;
  isCompatibleInput: (nodeId: NodeId, portId: PortId) => boolean;

  onSelect: (nodeId: NodeId) => void;
  onPointerDown: (event: MouseEvent<HTMLDivElement>, nodeId: NodeId) => void;

  onPortClick: (
    endpoint: GraphPortEndpoint,
    direction: PortDirection,
  ) => void;

  registerPort: (
    nodeId: NodeId,
    direction: PortDirection,
    portId: PortId,
    element: HTMLElement | null,
  ) => void;
}

function renderNodeIcon(descriptor: BlockDescriptor) {
  if (isSourceDescriptor(descriptor)) {
    if (isCodeDescriptor(descriptor)) {
      return <FileCode2 size={20} />;
    }

    return <FileInput size={20} />;
  }

  if (isOutputDescriptor(descriptor)) {
    if (descriptor.type.includes("artifact")) {
      return <FileOutput size={20} />;
    }

    return <UploadCloud size={20} />;
  }

  if (isMappingDescriptor(descriptor)) {
    return <Settings2 size={20} />;
  }

  if (isContextDescriptor(descriptor)) {
    return <Network size={20} />;
  }

  return <Box size={20} />;
}

function isSourceDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.capability?.namespace === "source" || descriptor.type.startsWith("source.");
}

function isCodeDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.type.includes(".code") || descriptor.defaultData.role === "code";
}

function isOutputDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.capability?.namespace === "target" ||
    descriptor.type.startsWith("target.") ||
    descriptor.type.includes("artifact") ||
    descriptor.category === "Outputs" ||
    descriptor.category === "Output" ||
    descriptor.category === "Target";
}

function isMappingDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.category === "Mapping" || descriptor.category === "Transform";
}

function isContextDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.category === "Context" || descriptor.category === "Environment";
}

function getNodeSize(node: GraphNodeModel, descriptor: BlockDescriptor) {
  const portRows = Math.max(
    descriptor.inputs.length,
    descriptor.outputs.length,
    1,
  );

  return {
    width: node.size?.width ?? descriptor.defaultSize?.width ?? 252,
    height: Math.max(
      node.size?.height ?? descriptor.defaultSize?.height ?? 168,
      112 + portRows * 34,
    ),
  };
}

function getDataPreviewEntries(node: GraphNodeModel) {
  return Object.entries(node.data).slice(0, 2);
}

export function GraphNode({
  node,
  descriptor,
  selected,
  pendingConnectionFrom,
  isCompatibleInput,
  onSelect,
  onPointerDown,
  onPortClick,
  registerPort,
}: GraphNodeProps) {
  const size = getNodeSize(node, descriptor);

  return (
    <div
      role="button"
      tabIndex={0}
      onMouseDown={(event) => onPointerDown(event, node.id)}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(node.id);
      }}
      className={[
        "absolute select-none rounded-3xl border bg-white shadow-sm transition",
        selected
          ? "border-slate-950 shadow-lg ring-4 ring-slate-200"
          : "border-slate-300 hover:border-slate-400 hover:shadow-md",
      ].join(" ")}
      style={{
        left: node.position.x,
        top: node.position.y,
        width: size.width,
        minHeight: size.height,
      }}
    >
      <div className="p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-2xl bg-slate-100 p-2.5 text-slate-700">
            {renderNodeIcon(descriptor)}
          </div>

          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold text-slate-950">
              {node.title}
            </div>

            <div className="mt-0.5 truncate text-xs text-slate-500">
              {descriptor.category}
            </div>
          </div>
        </div>

        <div className="mt-3 rounded-2xl bg-slate-50 p-3 text-xs text-slate-600">
          {getDataPreviewEntries(node).length === 0 ? (
            <div className="text-slate-400">No data</div>
          ) : (
            getDataPreviewEntries(node).map(([key, value]) => (
              <div key={key} className="flex gap-2">
                <span className="shrink-0 text-slate-400">{key}</span>
                <span className="truncate text-slate-700">
                  {String(value)}
                </span>
              </div>
            ))
          )}
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <div className="px-2 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Inputs
            </div>

            {descriptor.inputs.length === 0 ? (
              <div className="px-2 py-1.5 text-xs text-slate-300">none</div>
            ) : (
              descriptor.inputs.map((port) => (
                <PortButton
                  key={port.id}
                  nodeId={node.id}
                  port={port}
                  direction="input"
                  isPendingOutput={false}
                  isCompatibleInput={isCompatibleInput(node.id, port.id)}
                  onPortClick={onPortClick}
                  registerPort={registerPort}
                />
              ))
            )}
          </div>

          <div className="space-y-1">
            <div className="px-2 text-right text-[10px] font-semibold uppercase tracking-wide text-slate-400">
              Outputs
            </div>

            {descriptor.outputs.length === 0 ? (
              <div className="px-2 py-1.5 text-right text-xs text-slate-300">
                none
              </div>
            ) : (
              descriptor.outputs.map((port) => (
                <PortButton
                  key={port.id}
                  nodeId={node.id}
                  port={port}
                  direction="output"
                  isPendingOutput={
                    pendingConnectionFrom?.nodeId === node.id &&
                    pendingConnectionFrom?.portId === port.id
                  }
                  isCompatibleInput={false}
                  onPortClick={onPortClick}
                  registerPort={registerPort}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
