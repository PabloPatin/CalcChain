import { FolderOpen, X } from "lucide-react";

import type { Project } from "../../../shared/api/backendTypes";

export interface ProjectLoadDialogProps {
  projects: Project[];
  loading: boolean;
  onLoad: (project: Project) => void;
  onClose: () => void;
}

export function ProjectLoadDialog({
  projects,
  loading,
  onLoad,
  onClose,
}: ProjectLoadDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-6">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <div className="text-sm font-semibold text-slate-950">Загрузить проект</div>
            <div className="text-xs text-slate-500">Проекты хранятся в backend CalcChain.</div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-xl text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            aria-label="Закрыть"
          >
            <X size={18} />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-3">
          {loading ? (
            <div className="px-3 py-8 text-center text-sm text-slate-500">Загрузка проектов...</div>
          ) : projects.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm text-slate-500">Сохранённых проектов пока нет.</div>
          ) : (
            <div className="space-y-2">
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  onClick={() => onLoad(project)}
                  className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-left transition hover:border-slate-300 hover:bg-slate-50"
                >
                  <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-600">
                    <FolderOpen size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-slate-950">{project.name}</div>
                    <div className="truncate text-xs text-slate-500">
                      Обновлён {formatDate(project.updated_at)}
                    </div>
                  </div>
                  <div className="shrink-0 text-xs text-slate-400">
                    Нод: {project.graph.nodes.length}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}
