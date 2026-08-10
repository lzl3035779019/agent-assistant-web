import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { RunEvent } from "../api/types";
import { getAccessToken } from "../api/client";

export function useRunStream(runId: string | null) {
  const queryClient = useQueryClient();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    setEvents([]);
    if (!runId) {
      setConnected(false);
      return;
    }

    const accessToken = getAccessToken();
    const query = accessToken ? `?access_token=${encodeURIComponent(accessToken)}` : "";
    const stream = new EventSource(`/api/v1/runs/${runId}/events${query}`);
    stream.onopen = () => setConnected(true);
    stream.onerror = () => setConnected(false);

    const eventNames = [
      "run_started",
      "supervisor_decision",
      "agent_started",
      "agent_progress",
      "agent_completed",
      "run_completed",
      "run_failed",
      "run_cancelled",
      "agent_message",
      "agent_retry",
    ];
    const listeners = new Map<string, EventListener>();
    for (const eventName of eventNames) {
      const listener: EventListener = (rawEvent) => {
        const message = rawEvent as MessageEvent<string>;
        const event = JSON.parse(message.data) as RunEvent;
        setEvents((current) => {
          if (current.some((item) => item.id === event.id)) return current;
          return [...current, event].sort((a, b) => a.sequence - b.sequence);
        });
        if (["run_completed", "run_failed", "run_cancelled"].includes(event.event_type)) {
          void queryClient.invalidateQueries({ queryKey: ["run", runId] });
          stream.close();
          setConnected(false);
        }
      };
      listeners.set(eventName, listener);
      stream.addEventListener(eventName, listener);
    }

    return () => {
      for (const [eventName, listener] of listeners) {
        stream.removeEventListener(eventName, listener);
      }
      stream.close();
      setConnected(false);
    };
  }, [queryClient, runId]);

  return { events, connected };
}
