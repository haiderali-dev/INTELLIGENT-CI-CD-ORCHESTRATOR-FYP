import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether a media query matches now, re-rendering when that changes. `fallback` is the answer
 * where there is no `matchMedia` to ask, such as a test without one.
 */
export function useMediaQuery(query: string, fallback: boolean): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window.matchMedia !== "function") {
        return () => undefined;
      }
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => {
        list.removeEventListener("change", onChange);
      };
    },
    [query],
  );
  const read = () =>
    typeof window.matchMedia === "function" ? window.matchMedia(query).matches : fallback;
  return useSyncExternalStore(subscribe, read, () => fallback);
}

/** DESIGN.md section 7: the preview is a column from 1280 px, a drawer from 768 px, a sheet below. */
export const WIDE_QUERY = "(min-width: 80rem)";
export const MEDIUM_QUERY = "(min-width: 48rem)";
