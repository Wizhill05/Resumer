// WebSocket hook for real-time log streaming
"use client";
import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE } from "./api";
import type { LogEntry } from "./types";

export function useLogStream(path: string | null, maxEntries = 2000) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (!path) return;
    const url = `${WS_BASE}${path}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (evt) => {
      try {
        const entry: LogEntry = JSON.parse(evt.data);
        setLogs((prev) => {
          const next = [...prev, entry];
          return next.length > maxEntries ? next.slice(next.length - maxEntries) : next;
        });
      } catch {}
    };

    ws.onclose = () => {
      reconnectTimer.current = setTimeout(connect, 3000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [path, maxEntries]);

  useEffect(() => {
    setLogs([]);
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const clear = useCallback(() => setLogs([]), []);

  return { logs, clear };
}
