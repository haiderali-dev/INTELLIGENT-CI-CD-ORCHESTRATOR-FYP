import { Toast } from "radix-ui";
import { useCallback, useRef, useState, type ReactNode } from "react";

import { ToastContext } from "./toastContext";

interface Item {
  id: number;
  message: string;
}

/**
 * Toasts confirm an action in the words of the action (DESIGN.md principle 4): Approve and run
 * ends in "Run started". A floating layer, so 8px corners and the one shadow, a Rule border in
 * dark mode; it slides in over 160 ms and not at all under reduced motion. Radix announces each
 * one politely to screen readers.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const nextId = useRef(0);

  const show = useCallback((message: string) => {
    nextId.current += 1;
    const id = nextId.current;
    setItems((current) => [...current, { id, message }]);
  }, []);

  return (
    <ToastContext value={show}>
      <Toast.Provider duration={5000} swipeDirection="right" label="Notification">
        {children}
        {items.map(({ id, message }) => (
          <Toast.Root
            key={id}
            onOpenChange={(open) => {
              if (!open) {
                setItems((current) => current.filter((item) => item.id !== id));
              }
            }}
            className="rounded-float bg-panel px-4 py-3 text-base font-semibold text-ink shadow-float data-[state=open]:animate-[toast-in_160ms_ease-out] dark:border dark:border-rule"
          >
            <Toast.Title>{message}</Toast.Title>
          </Toast.Root>
        ))}
        <Toast.Viewport className="fixed right-4 bottom-4 z-50 flex w-[22rem] max-w-[calc(100vw-2rem)] flex-col gap-2" />
      </Toast.Provider>
    </ToastContext>
  );
}
