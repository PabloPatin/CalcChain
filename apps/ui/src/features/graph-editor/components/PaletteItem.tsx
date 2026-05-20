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

function getPaletteIcon(descriptor: BlockDescriptor) {
  if (descriptor.category === "Sources") {
    if (descriptor.capability?.namespace === "source" && descriptor.defaultData.role === "code") {
      return FileCode2;
    }

    return FileInput;
  }

  if (descriptor.category === "Outputs") {
    if (descriptor.type.includes("artifact")) {
      return FileOutput;
    }

    return UploadCloud;
  }

  if (descriptor.category === "Mapping") {
    return Settings2;
  }

  if (descriptor.category === "Context") {
    return Network;
  }

  return Box;
}

export function PaletteItem({
  descriptor,
  onAddAtCenter,
  onDragStart,
}: PaletteItemProps) {
  const Icon = getPaletteIcon(descriptor);

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
          <Icon size={18} />
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