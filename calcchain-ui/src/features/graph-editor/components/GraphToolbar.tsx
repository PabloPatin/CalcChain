import { Play, RotateCcw, Save, X } from "lucide-react";

export interface GraphToolbarProps {
  message?: string;

  isCreatingConnection: boolean;

  onSave?: () => void;
  onValidate?: () => void;
  onRun?: () => void;
  onClear?: () => void;
  onCancelConnection?: () => void;
}

export function GraphToolbar({
  message,
  isCreatingConnection,
  onSave,
  onValidate,
  onRun,
  onClear,
  onCancelConnection,
}: GraphToolbarProps) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white/80 px-6 backdrop-blur">
      <div>
        <div className="text-sm font-semibold text-slate-950">Workspace</div>
        <div className="text-xs text-slate-500">
          {message ?? "Собери расчётный граф из блоков."}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {isCreatingConnection && (
          <button
            type="button"
            onClick={onCancelConnection}
            className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <X size={16} />
            Cancel connection
          </button>
        )}

        <button
          type="button"
          onClick={onSave}
          className="flex items-center gap-2 rounded-2xl bg-slate-950 px-4 py-2 text-sm font-medium text-white shadow-sm"
        >
          <Save size={16} />
          Save
        </button>

        <button
          type="button"
          onClick={onValidate}
          className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <Play size={16} />
          Validate
        </button>

        {onRun && (
          <button
            type="button"
            onClick={onRun}
            className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <Play size={16} />
            Run
          </button>
        )}

        <button
          type="button"
          onClick={onClear}
          className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          <RotateCcw size={16} />
          Clear
        </button>
      </div>
    </header>
  );
}