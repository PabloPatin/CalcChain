import type { DragEvent } from "react";
import { Box, FileCode2, FileInput, FileOutput, Settings2, UploadCloud, Network } from "lucide-react";

import type { BlockDescriptor } from "../model/types";

export interface PaletteItemProps {
  descriptor: BlockDescriptor;
  onAddAtCenter: (descriptor: BlockDescriptor) => void;
  onDragStart: (
    event: DragEvent<HTMLButtonElement>,
    descriptor: BlockDescriptor,
  ) => void;
}

function renderPaletteIcon(descriptor: BlockDescriptor) {
  if (isSourceDescriptor(descriptor)) {
    if (isCodeDescriptor(descriptor)) {
      return <FileCode2 size={18} />;
    }

    return <FileInput size={18} />;
  }

  if (isOutputDescriptor(descriptor)) {
    if (descriptor.type.includes("artifact")) {
      return <FileOutput size={18} />;
    }

    return <UploadCloud size={18} />;
  }

  if (isMappingDescriptor(descriptor)) {
    return <Settings2 size={18} />;
  }

  if (isContextDescriptor(descriptor)) {
    return <Network size={18} />;
  }

  return <Box size={18} />;
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
    descriptor.category === "Target" ||
    descriptor.category === "Результаты" ||
    descriptor.category === "Назначения";
}

function isMappingDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.type === "rule-set" ||
    descriptor.category === "Mapping" ||
    descriptor.category === "Transform" ||
    descriptor.category === "Правила";
}

function isContextDescriptor(descriptor: BlockDescriptor): boolean {
  return descriptor.category === "Context" ||
    descriptor.category === "Environment" ||
    descriptor.category === "Окружение";
}

export function PaletteItem({
  descriptor,
  onAddAtCenter,
  onDragStart,
}: PaletteItemProps) {
  return (
    <button
      type="button"
      draggable
      onDragStart={(event) => onDragStart(event, descriptor)}
      onDoubleClick={() => onAddAtCenter(descriptor)}
      className="group w-full rounded-2xl border border-slate-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
    >
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-slate-100 p-2 text-slate-700 group-hover:bg-slate-200">
          {renderPaletteIcon(descriptor)}
        </div>

        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-slate-900">
            {descriptor.title}
          </div>

          {descriptor.description && (
            <div className="mt-1 line-clamp-2 text-xs leading-4 text-slate-500">
              {descriptor.description}
            </div>
          )}
        </div>
      </div>
    </button>
  );
}
