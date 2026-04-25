import type { Sample } from "./types";

type Listener = (s: Sample) => void;

// Reconnecting WebSocket client. The obd2 daemon restarts on adapter
// errors (PRD §6.2 failure modes), so the UI must tolerate dropped
// connections without user-visible errors.
export class SampleStream {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private url: string;
  private backoffMs = 500;
  private stopped = false;

  constructor(url: string) {
    this.url = url;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.ws?.close();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private connect(): void {
    if (this.stopped) return;
    this.ws = new WebSocket(this.url);
    this.ws.onopen = () => {
      this.backoffMs = 500;
    };
    this.ws.onmessage = (ev) => {
      try {
        const s = JSON.parse(ev.data) as Sample;
        for (const l of this.listeners) l(s);
      } catch {
        // Ignore malformed frames — the daemon should never send them.
      }
    };
    this.ws.onclose = () => {
      if (this.stopped) return;
      setTimeout(() => this.connect(), this.backoffMs);
      this.backoffMs = Math.min(this.backoffMs * 2, 10_000);
    };
    this.ws.onerror = () => {
      this.ws?.close();
    };
  }
}
