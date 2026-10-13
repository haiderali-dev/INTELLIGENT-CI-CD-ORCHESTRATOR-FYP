import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import { THEME_PREFERENCES, type ThemePreference } from "@/app/theme/theme";
import { useTheme } from "@/app/theme/themeContext";
import { cn } from "@/lib/cn";

const OPTIONS: Record<ThemePreference, { label: string; icon: LucideIcon }> = {
  light: { label: "Light", icon: Sun },
  dark: { label: "Dark", icon: Moon },
  system: { label: "System", icon: Monitor },
};

/** Light, Dark or System, as native radio buttons: arrow keys move between them. */
export function ThemeSwitch() {
  const { preference, setPreference } = useTheme();

  return (
    <fieldset className="min-w-0">
      <legend className="mb-1 text-sm text-graphite">Theme</legend>
      <div className="flex gap-1">
        {THEME_PREFERENCES.map((value) => {
          const { label, icon: Icon } = OPTIONS[value];
          return (
            <label key={value} className="relative">
              <input
                type="radio"
                name="theme"
                value={value}
                checked={preference === value}
                onChange={() => {
                  setPreference(value);
                }}
                className="peer absolute inset-0 cursor-pointer opacity-0"
              />
              <span
                className={cn(
                  "flex items-center gap-1 rounded-control border border-graphite px-2 py-1 text-sm",
                  "peer-checked:bg-ink peer-checked:text-panel",
                  "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink",
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
                {label}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
