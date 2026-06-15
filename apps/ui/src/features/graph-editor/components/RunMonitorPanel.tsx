import type {
  ArtifactSummary,
  LogItem,
  RunDetails,
  RunEvent,
} from "../../../shared/api/backendTypes";

export interface RunMonitorPanelProps {
  run: RunDetails | null;
  events: RunEvent[];
  logs: LogItem[];
  artifacts: ArtifactSummary[];
}

export function RunMonitorPanel({
  run,
  events,
  logs,
  artifacts,
}: RunMonitorPanelProps) {
  if (run === null && events.length === 0) {
    return null;
  }

  return (
    <section className="border-b border-slate-200 bg-white px-6 py-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Расчёт
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-slate-950">
              {run?.id ?? "запускается"}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
              {run ? formatRunStatus(run.status) : "в очереди"}
            </span>
            {run?.error && (
              <span className="text-xs text-red-600">{run.error}</span>
            )}
          </div>
          {run?.progress && Object.keys(run.progress).length > 0 && (
            <pre className="mt-2 max-w-xl overflow-hidden text-ellipsis rounded-lg bg-slate-50 px-2 py-1 text-xs text-slate-600">
              {JSON.stringify(run.progress)}
            </pre>
          )}
        </div>

        <div className="grid min-w-[320px] flex-1 grid-cols-3 gap-3 text-xs">
          <SummaryList
            title="События"
            items={events.slice(-4).map((event) => `${event.type} #${event.id}`)}
          />
          <SummaryList
            title="Логи"
            items={logs.slice(-4).map((item) => `${item.level}: ${item.message}`)}
          />
          <SummaryList
            title="Артефакты"
            items={artifacts.slice(0, 4).map((artifact) => artifact.name)}
          />
        </div>
      </div>
    </section>
  );
}

function SummaryList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </div>
      <div className="mt-1 space-y-1">
        {items.length === 0 ? (
          <div className="text-slate-300">нет</div>
        ) : (
          items.map((item, index) => (
            <div key={`${item}-${index}`} className="truncate text-slate-600">
              {item}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function formatRunStatus(status: string): string {
  const labels: Record<string, string> = {
    queued: "в очереди",
    running: "выполняется",
    success: "успешно",
    failed: "ошибка",
    cancelled: "отменён",
  };

  return labels[status] ?? status;
}
