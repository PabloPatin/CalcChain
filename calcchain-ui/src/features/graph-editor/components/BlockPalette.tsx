import type { DragEvent } from "react";

import type { BlockDescriptor } from "../model/types";
import { groupBlockDescriptorsByCategory } from "../model/blockDescriptors";

import { PaletteItem } from "./PaletteItem";

export interface BlockPaletteProps {
  descriptors: BlockDescriptor[];
  onAddAtCenter: (descriptor: BlockDescriptor) => void;
  onDragStart: (
    event: DragEvent<HTMLButtonElement>,
    descriptor: BlockDescriptor,
  ) => void;
}

export function BlockPalette({
  descriptors,
  onAddAtCenter,
  onDragStart,
}: BlockPaletteProps) {
  const groups = groupBlockDescriptorsByCategory(descriptors);

  return (
    <aside className="w-80 shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-950">
          CalcChain UI
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Конструктор расчётных блоков
        </p>
      </div>

      <div className="mt-6 rounded-3xl bg-slate-50 p-4 text-sm text-slate-600">
        <div className="font-semibold text-slate-900">Как работать</div>
        <p className="mt-2 leading-5">
          Перетащи блок на рабочую область или дважды кликни по нему, чтобы
          добавить в центр видимой области.
        </p>
      </div>

      <div className="mt-6 space-y-6">
        {Object.entries(groups).map(([category, categoryDescriptors]) => (
          <section key={category}>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
                {category}
              </h2>

              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {categoryDescriptors.length}
              </span>
            </div>

            <div className="space-y-2">
              {categoryDescriptors.map((descriptor) => (
                <PaletteItem
                  key={descriptor.type}
                  descriptor={descriptor}
                  onAddAtCenter={onAddAtCenter}
                  onDragStart={onDragStart}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
}