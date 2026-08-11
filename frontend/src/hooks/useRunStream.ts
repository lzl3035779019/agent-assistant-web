import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import type { RunEvent } from "../api/types";
import { buildApiUrl, getAccessToken } from "../api/client";

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

    const controller = new AbortController();
    const accessToken = getAccessToken();
    const streamUrl = buildApiUrl(`/runs/${runId}/events`);

    const consumeStream = async () => {
      const headers = new Headers({ Accept: "text/event-stream" });
      if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
      if (/\.ngrok-free\.(app|dev)(?:\/|$)/i.test(streamUrl)) {
        headers.set("ngrok-skip-browser-warning", "1");
      }

      try {
        const response = await fetch(streamUrl, {
          headers,
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`SSE connection failed: ${response.status}`);
        }
        setConnected(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const consumeFrame = (frame: string) => {
          const data = frame
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart())
            .join("\n");
          if (!data) return;

          try {
            const event = JSON.parse(data) as RunEvent;
            setEvents((current) => {
              if (current.some((item) => item.id === event.id)) return current;
              return [...current, event].sort((a, b) => a.sequence - b.sequence);
            });
            if (["run_completed", "run_failed", "run_cancelled"].includes(event.event_type)) {
              void queryClient.invalidateQueries({ queryKey: ["run", runId] });
              setConnected(false);
            }
          } catch {
            // Ignore malformed frames and continue consuming later events.
          }
        };

        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            consumeFrame(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");
          }
        }
        buffer += decoder.decode();
        if (buffer.trim()) consumeFrame(buffer);
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("Run event stream disconnected", error);
        }
      } finally {
        setConnected(false);
      }
    };

    void consumeStream();

    return () => {
      controller.abort();
      setConnected(false);
    };
  }, [queryClient, runId]);

  return { events, connected };
}
