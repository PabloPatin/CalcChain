import type {
  GraphPortEndpoint,
  NodeId,
  PortDescriptor,
  PortDirection,
  PortId,
} from "../model/types";

export interface PortButtonProps {
  nodeId: NodeId;
  port: PortDescriptor;
  direction: PortDirection;

  isPendingOutput: boolean;
  isCompatibleInput: boolean;

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

export function PortButton({
  nodeId,
  port,
  direction,
  isPendingOutput,
  isCompatibleInput,
  onPortClick,
  registerPort,
}: PortButtonProps) {
  const isOutput = direction === "output";

  const className = [
    "relative flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-xs transition",
    isOutput ? "justify-end pr-4 text-right" : "justify-start pl-4 text-left",
    isPendingOutput
      ? "bg-slate-950 text-white"
      : isCompatibleInput
        ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
        : "text-slate-600 hover:bg-slate-100",
  ].join(" ");

  return (
    <button
      type="button"
      title={port.description ?? port.kind}
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();

        onPortClick(
          {
            node_id: nodeId,
            port_id: port.id,
          },
          direction,
        );
      }}
      className={className}
    >
      {!isOutput && (
        <span
          ref={(element) =>
            registerPort(nodeId, direction, port.id, element)
          }
          className="absolute -left-[23px] top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border-2 border-current bg-white shadow-sm"
        />
      )}

      <span className="truncate">{port.label}</span>

      {isOutput && (
        <span
          ref={(element) =>
            registerPort(nodeId, direction, port.id, element)
          }
          className="absolute -right-[23px] top-1/2 h-4 w-4 -translate-y-1/2 rounded-full border-2 border-current bg-white shadow-sm"
        />
      )}
    </button>
  );
}
