import { useEffect, useRef, useState } from "react";

/**
 * Subscribe to one of the server's Server-Sent-Event channels:
 *   - "mentions" — new mentions persisted by the ingestion layer
 *   - "alerts"   — new alerts created by the alert engine
 *   - "signals"  — anomaly / momentum signal events
 *
 * The browser `EventSource` API cannot set request headers, so we pass the
 * access token as a `?token=` query param. The backend accepts either form.
 *
 * Returns:
 *   - status: "connecting" | "open" | "error" | "closed"
 *   - events: a rolling buffer of the last `bufferSize` payloads
 *   - lastEvent: the most recent payload (or null)
 */
export type LiveStatus = "connecting" | "open" | "error" | "closed";

export interface LiveStreamOptions {
  bufferSize?: number;
  enabled?: boolean;
}

export function useLiveStream<T = any>(
  channel: "mentions" | "alerts" | "signals",
  { bufferSize = 25, enabled = true }: LiveStreamOptions = {}
) {
  const [status, setStatus] = useState<LiveStatus>("closed");
  const [events, setEvents] = useState<T[]>([]);
  const [lastEvent, setLastEvent] = useState<T | null>(null);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const token = localStorage.getItem("access_token");
    if (!token) return;

    const url = `/api/v1/stream/${channel}?token=${encodeURIComponent(token)}`;
    setStatus("connecting");
    const es = new EventSource(url);
    esRef.current = es;

    const push = (payload: T) => {
      setLastEvent(payload);
      setEvents((prev) => {
        const next = [payload, ...prev];
        if (next.length > bufferSize) next.length = bufferSize;
        return next;
      });
    };

    es.addEventListener("open", () => setStatus("open"));
    es.onopen = () => setStatus("open");

    const onMessage = (e: MessageEvent) => {
      try {
        push(JSON.parse(e.data));
      } catch {
        /* ignore malformed frames */
      }
    };

    // Listen for both named SSE events (`event: mention.created`) and
    // the default `message` event. We register a few named handlers since
    // browsers route by event name.
    [
      "message",
      "mention.created",
      "alert.created",
      "signal.anomaly",
      "signal.momentum",
    ].forEach((name) => es.addEventListener(name, onMessage));

    es.onerror = () => {
      setStatus("error");
      // Don't close — EventSource auto-reconnects with backoff.
    };

    return () => {
      es.close();
      esRef.current = null;
      setStatus("closed");
    };
  }, [channel, enabled, bufferSize]);

  return { status, events, lastEvent };
}
