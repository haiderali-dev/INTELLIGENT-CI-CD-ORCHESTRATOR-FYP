import { THEME_PREFERENCES, type ThemePreference } from "@/app/theme/theme";
import { useTheme } from "@/app/theme/themeContext";
import { cn } from "@/lib/cn";

const OPTIONS: Record<ThemePreference, { label: string }> = {
  light: { label: "Light" },
  dark: { label: "Dark" },
  system: { label: "System" },
};

/** Light, Dark or System, as native radio buttons: arrow keys move between them. */
export function ThemeSwitch() {
  const { preference, setPreference } = useTheme();

  return (
    // Three equal parts, words only: with icons the three were 229px wide, and the sidebar's footer
    // has 192px, so System ran out of it (seen in T6.9's screenshots).
    <fieldset className="w-full max-w-56 min-w-0">
      <legend className="mb-1 text-sm text-graphite">Theme</legend>
      <div className="grid grid-cols-3 gap-1">
        {THEME_PREFERENCES.map((value) => {
          const { label } = OPTIONS[value];
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
                  "flex items-center justify-center rounded-control border border-graphite px-1 py-1 text-sm max-md:min-h-11",
                  "peer-checked:bg-ink peer-checked:text-panel",
                  "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink",
                )}
              >
                {label}
              </span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
