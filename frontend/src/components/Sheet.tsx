import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type SheetSide = "left" | "right" | "bottom";

const PLACEMENT: Record<SheetSide, string> = {
  left: "inset-y-0 left-0 w-80 max-w-[85vw] rounded-r-float dark:border-r",
  right: "inset-y-0 right-0 w-[26rem] max-w-[90vw] rounded-l-float dark:border-l",
  bottom: "inset-x-0 bottom-0 max-h-[85dvh] rounded-t-float dark:border-t",
};

/**
 * A drawer or bottom sheet (4.7.4: under 1280 px the preview is a drawer, under 768 px a bottom
 * sheet). A floating layer, so 8px corners on its open side, the one shadow in light mode and a
 * Rule border in dark. Focus moves in on open and back to the trigger on close.
 */
export function Sheet({
  side,
  title,
  trigger,
  open,
  onOpenChange,
  onOpenAutoFocus,
  children,
}: {
  side: SheetSide;
  title: string;
  trigger: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenAutoFocus?: (event: Event) => void;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Trigger asChild>{trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content
          onOpenAutoFocus={onOpenAutoFocus}
          aria-describedby={undefined}
          className={cn(
            "fixed z-50 flex flex-col bg-panel text-ink shadow-float dark:border-rule",
            PLACEMENT[side],
          )}
        >
          <div className="flex items-center justify-between gap-2 border-b border-rule py-1 pr-1 pl-4">
            <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label={`Close ${title.toLowerCase()}`}
                className="inline-flex size-11 items-center justify-center rounded-control"
              >
                <X aria-hidden="true" className="size-5" />
              </button>
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
