import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { setAccessToken, setTokenRefresher } from "@/api/client";

// jsdom does no layout, and leaves out the browser APIs that only make sense with one. These stubs
// report the nothing that jsdom's layout is: Radix measures with ResizeObserver, CodeMirror reads
// rectangles from ranges, and the thread scrolls its newest message into view.
class NoLayoutResizeObserver implements ResizeObserver {
  observe(): void {
    // Nothing is ever resized without layout.
  }
  unobserve(): void {
    // Nothing to stop observing.
  }
  disconnect(): void {
    // Nothing to disconnect.
  }
}
function noRects(): DOMRectList {
  return Object.assign([], { item: () => null });
}

// jsdom 29 has none of these (checked 2026-10-15), so they are set, not filled in.
globalThis.ResizeObserver = NoLayoutResizeObserver;
Range.prototype.getClientRects = noRects;
Range.prototype.getBoundingClientRect = () => new DOMRect();
Element.prototype.scrollIntoView = () => undefined;

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
  delete document.documentElement.dataset.theme;
  // The API client's token and refresher are module state, shared by every test in a file.
  setAccessToken(null);
  setTokenRefresher(null);
});
