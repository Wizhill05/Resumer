"use client";
import { useEffect, useRef } from "react";
import { clsx } from "clsx";
import type { LogEntry } from "@/lib/types";

interface LogViewerProps {
  logs: LogEntry[];
  height?: string;
  autoScroll?: boolean;
}

export default function LogViewer({ logs, height = "h-64", autoScroll = true }: LogViewerProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "instant" });
    }
  }, [logs, autoScroll]);

  return (
    <div
      className={clsx(
        "bg-neutral-950 border border-neutral-800 rounded overflow-auto log-viewer p-2",
        height
      )}
    >
      {logs.length === 0 ? (
        <p className="text-neutral-600 text-xs">No logs yet.</p>
      ) : (
        logs.map((entry, i) => (
          <div
            key={i}
            className={clsx("whitespace-pre-wrap break-all", `log-${entry.level}`)}
          >
            <span className="text-neutral-600 select-none mr-1">
              {new Date(entry.ts * 1000).toLocaleTimeString()}
            </span>
            {entry.text}
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  );
}
