import { ACCENT_TEXT } from "@/app/shell/nav";
import { button } from "@/components/button";
import { cn } from "@/lib/cn";

import { ASSISTANTS, type AssistantKind } from "./assistants";

/**
 * A new chat (4.7.4): one sentence on what this assistant creates, four example commands to click,
 * and the services it knows. An empty state invites an action (4.7.5).
 */
export function EmptyState({
  assistant,
  services,
  onExample,
}: {
  assistant: AssistantKind;
  services: readonly string[];
  onExample: (command: string) => void;
}) {
  const { icon: Icon, accent, creates, examples } = ASSISTANTS[assistant];
  return (
    <div className="flex max-w-[68ch] flex-col gap-6">
      <Icon aria-hidden="true" className={cn("size-8", ACCENT_TEXT[accent])} />
      <p>{creates}</p>
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Try one of these</h2>
        <ul className="flex flex-col gap-2">
          {examples.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => {
                  onExample(example);
                }}
                className={cn(button(), "h-auto min-h-10 w-full justify-start py-2 text-left font-normal")}
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-sm">
        <span className="text-graphite">Services it knows: </span>
        {services.length > 0
          ? services.join(", ")
          : "none yet. An administrator adds them to the catalog."}
      </p>
    </div>
  );
}
