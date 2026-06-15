import { CheckCircle2, FileJson, FilePlus2, FolderOpen, Rocket, Save } from "lucide-react";

export interface GraphToolbarProps {
  message?: string;
  busyAction: "validate" | "compile-run" | "import" | null;
  projectBusy: boolean;
  projectName: string;
  activeProjectId: string | null;
  onProjectNameChange: (name: string) => void;
  onNewProject: () => void;
  onSave: () => void;
  onLoad: () => void;
  onImportManifest: () => void;
  onValidate: () => void;
  onCompileRun: () => void;
}

export function GraphToolbar({
  message,
  busyAction,
  projectBusy,
  projectName,
  activeProjectId,
  onProjectNameChange,
  onNewProject,
  onSave,
  onLoad,
  onImportManifest,
  onValidate,
  onCompileRun,
}: GraphToolbarProps) {
  const disabled = busyAction !== null || projectBusy;
  const secondaryButtonClass =
    "flex h-9 min-w-20 items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:hover:bg-white";
  const primaryButtonClass =
    "flex h-9 min-w-36 items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:hover:bg-slate-950";

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-6 backdrop-blur">
      <div className="min-w-0 flex-1 pr-4">
        <div className="flex min-w-0 items-center gap-3">
          <input
            value={projectName}
            onChange={(event) => onProjectNameChange(event.target.value)}
            disabled={disabled}
            aria-label="Название проекта"
            className="h-8 w-64 min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-950 outline-none transition focus:border-slate-400 disabled:bg-slate-50"
            placeholder="Название проекта"
          />
          <div className="shrink-0 text-xs text-slate-400">
            {activeProjectId === null ? "Проект не сохранён" : "Проект сохранён"}
          </div>
        </div>
        <div className="truncate text-xs text-slate-500">
          {message ?? "Соберите граф расчёта из блоков."}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onNewProject}
          disabled={disabled}
          aria-label="Новый"
          title="Новый"
          className={secondaryButtonClass}
        >
          <FilePlus2 size={16} />
        </button>

        <button
          type="button"
          onClick={onSave}
          disabled={disabled}
          aria-label="Сохранить"
          title="Сохранить"
          className={secondaryButtonClass}
        >
          <Save size={16} />
        </button>

        <button
          type="button"
          onClick={onLoad}
          disabled={disabled}
          aria-label="Загрузить"
          title="Загрузить"
          className={secondaryButtonClass}
        >
          <FolderOpen size={16} />
        </button>

        <button
          type="button"
          onClick={onImportManifest}
          disabled={disabled}
          aria-busy={busyAction === "import"}
          className={secondaryButtonClass}
        >
          <FileJson size={16} />
          Импорт
        </button>

        <button
          type="button"
          onClick={onValidate}
          disabled={disabled}
          aria-busy={busyAction === "validate"}
          className={secondaryButtonClass}
        >
          <CheckCircle2 size={16} />
          Проверить
        </button>

        <button
          type="button"
          onClick={onCompileRun}
          disabled={disabled}
          aria-busy={busyAction === "compile-run"}
          className={primaryButtonClass}
        >
          <Rocket size={16} />
          Запуск
        </button>
      </div>
    </header>
  );
}
