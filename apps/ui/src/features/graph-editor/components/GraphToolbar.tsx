import { CheckCircle2, FolderOpen, Rocket, Save } from "lucide-react";

export interface GraphToolbarProps {
  message?: string;
  busyAction: "validate" | "compile-run" | null;
  onSave: () => void;
  onLoad: () => void;
  onValidate: () => void;
  onCompileRun: () => void;
}

export function GraphToolbar({
  message,
  busyAction,
  onSave,
  onLoad,
  onValidate,
  onCompileRun,
}: GraphToolbarProps) {
  const disabled = busyAction !== null;
  const secondaryButtonClass =
    "flex h-9 min-w-24 items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:hover:bg-white";
  const primaryButtonClass =
    "flex h-9 min-w-36 items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:hover:bg-slate-950";

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-6 backdrop-blur">
      <div className="min-w-0">
        <div className="text-sm font-semibold text-slate-950">Workspace</div>
        <div className="truncate text-xs text-slate-500">
          {message ?? "Собери расчетный граф из блоков."}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={disabled}
          className={secondaryButtonClass}
        >
          <Save size={16} />
          Save
        </button>

        <button
          type="button"
          onClick={onLoad}
          disabled={disabled}
          className={secondaryButtonClass}
        >
          <FolderOpen size={16} />
          Load
        </button>

        <button
          type="button"
          onClick={onValidate}
          disabled={disabled}
          aria-busy={busyAction === "validate"}
          className={secondaryButtonClass}
        >
          <CheckCircle2 size={16} />
          Validate
        </button>

        <button
          type="button"
          onClick={onCompileRun}
          disabled={disabled}
          aria-busy={busyAction === "compile-run"}
          className={primaryButtonClass}
        >
          <Rocket size={16} />
          Compile + Run
        </button>
      </div>
    </header>
  );
}
