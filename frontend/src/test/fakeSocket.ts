import type { SocketLike } from "@/ws/LiveEventsClient";

/** A WebSocket the test plays the server for. Every socket created is kept in `opened`. */
export class FakeSocket implements SocketLike {
  static opened: FakeSocket[] = [];
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  sent: string[] = [];
  closedWith: number | undefined;

  constructor(readonly url: string) {
    FakeSocket.opened.push(this);
  }

  static latest(): FakeSocket | null {
    return FakeSocket.opened.at(-1) ?? null;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code?: number): void {
    this.closedWith = code;
  }

  // What the server does.
  accept(): void {
    this.onopen?.(new Event("open"));
  }

  deliver(payload: unknown): void {
    const data = typeof payload === "string" ? payload : JSON.stringify(payload);
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  drop(code: number): void {
    this.onclose?.(new CloseEvent("close", { code }));
  }
}
