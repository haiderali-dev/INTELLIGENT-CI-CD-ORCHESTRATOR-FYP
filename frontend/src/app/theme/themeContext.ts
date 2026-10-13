import { createContext, useContext } from "react";

import type { ResolvedTheme, ThemePreference } from "./theme";

export interface ThemeState {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeState | null>(null);

export function useTheme(): ThemeState {
  const state = useContext(ThemeContext);
  if (!state) {
    throw new Error("useTheme needs a <ThemeProvider> above it");
  }
  return state;
}
