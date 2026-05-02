import { clsx } from "clsx";

const STATUS_COLORS: Record<string, string> = {
  idle:        "bg-neutral-800 text-neutral-400",
  starting:    "bg-yellow-900 text-yellow-300",
  running:     "bg-blue-900 text-blue-300",
  completed:   "bg-green-900 text-green-300",
  failed:      "bg-red-900 text-red-300",
  stopping:    "bg-orange-900 text-orange-300",
  stopped:     "bg-neutral-800 text-neutral-400",
  // Job statuses
  new:         "bg-neutral-800 text-neutral-400",
  saved:       "bg-blue-900 text-blue-300",
  queued:      "bg-yellow-900 text-yellow-300",
  generating:  "bg-blue-900 text-blue-300",
  generated:   "bg-green-900 text-green-300",
  applied:     "bg-green-800 text-green-200",
  skipped:     "bg-neutral-800 text-neutral-500",
  // Batch statuses
  draft:       "bg-neutral-800 text-neutral-400",
  paused:      "bg-yellow-900 text-yellow-300",
  // Description statuses
  ready:       "bg-green-900 text-green-300",
  missing:     "bg-neutral-800 text-neutral-500",
  // Other
  ok:          "bg-green-900 text-green-300",
  error:       "bg-red-900 text-red-300",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-neutral-800 text-neutral-400";
  return (
    <span className={clsx("inline-block text-xs px-1.5 py-0.5 rounded font-mono uppercase", cls)}>
      {status}
    </span>
  );
}
