import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// How long `findBy` and `waitFor` wait for something to appear. Testing Library's default, one
// second, is an assumption about the machine: a page drawn cold, its lazily loaded module included,
// takes longer while eight workers share the CPU with the gate's other work, and the Phase 6 gate of
// 2026-10-20 failed a page test that way (and a second failed in two of three runs after). Waiting
// longer changes no assertion: what must appear still must, and what is missing still fails.
configure({ asyncUtilTimeout: 5_000 });

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
