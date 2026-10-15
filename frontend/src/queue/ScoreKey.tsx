import { Switch } from "radix-ui";
import { useId } from "react";

import { FACTORS } from "@/components/scoreBarModel";
import { cn } from "@/lib/cn";

/** What the bars' four colours stand for, in the formula's order. The keys carry the hue; the
 * words stay in Ink (DESIGN.md section 2). */
export function ScoreKey() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <span className="font-semibold">Key</span>
      <ul aria-label="Score bar key" className="flex flex-wrap gap-x-4 gap-y-1">
        {FACTORS.map(({ key, label, fill }) => (
          <li key={key} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("size-2.5 rounded-control", fill)} />
            {label}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Adds each bar's four contributions as numbers (DESIGN.md section 6), for anyone who would
 * rather read them than compare lengths. */
export function NumbersSwitch({
  checked,
  onCheckedChange,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-2 max-md:min-h-11">
      <Switch.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        className="relative inline-flex h-6 w-11 shrink-0 items-center rounded-control border border-graphite bg-panel data-[state=checked]:border-ink data-[state=checked]:bg-ink"
      >
        <Switch.Thumb className="block size-4 translate-x-[3px] rounded-control bg-graphite transition-transform duration-150 data-[state=checked]:translate-x-[23px] data-[state=checked]:bg-panel" />
      </Switch.Root>
      <label htmlFor={id} className="text-base">
        Show the numbers
      </label>
    </div>
  );
}
