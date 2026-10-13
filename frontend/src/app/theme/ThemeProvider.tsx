import { useCallback, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";

import {
  applyTheme,
  readPreference,
  resolveTheme,
  storePreference,
  systemPrefersDark,
  watchSystemTheme,
  type ThemePreference,
} from "./theme";
import { ThemeContext, type ThemeState } from "./themeContext";

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const prefersDark = useSyncExternalStore(watchSystemTheme, systemPrefersDark, () => false);
  const resolved = resolveTheme(preference, prefersDark);

  useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  const setPreference = useCallback((next: ThemePreference) => {
    storePreference(next);
    setPreferenceState(next);
  }, []);

  const value = useMemo<ThemeState>(
    () => ({ preference, resolved, setPreference }),
    [preference, resolved, setPreference],
  );

  return <ThemeContext value={value}>{children}</ThemeContext>;
}
