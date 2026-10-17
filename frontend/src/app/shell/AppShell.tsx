import { Menu, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";
import { Outlet } from "react-router";

import { PRODUCT_NAME } from "./nav";
import { Sidebar } from "./Sidebar";

/**
 * The frame every signed-in page sits in. From 768 px a sidebar; below it, a top bar whose menu
 * button opens the same sidebar as a sheet, and Staging moves into the bar (DESIGN.md section 4).
 */
export function AppShell() {
  return (
    <div className="min-h-dvh bg-ground text-ink md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-panel focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <aside className="hidden md:sticky md:top-0 md:block md:h-dvh">
        <Sidebar />
      </aside>

      <MobileBar />

      <main id="main" tabIndex={-1} className="min-h-dvh bg-panel md:border-l md:border-rule">
        <Outlet />
      </main>
    </div>
  );
}

function MobileBar() {
  const [open, setOpen] = useState(false);

  return (
    <header className="flex items-center gap-3 border-b border-rule bg-panel px-4 py-2 md:hidden">
      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Trigger asChild>
          <button
            type="button"
            aria-label="Open navigation"
            className="-ml-2 inline-flex size-11 items-center justify-center rounded-control"
          >
            <Menu aria-hidden="true" className="size-5" />
          </button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
          <Dialog.Content
            aria-describedby={undefined}
            className="fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-transparent bg-ground shadow-float dark:border-rule"
          >
            <Dialog.Title className="sr-only">Navigation</Dialog.Title>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close navigation"
                className="absolute top-2 right-2 inline-flex size-11 items-center justify-center rounded-control"
              >
                <X aria-hidden="true" className="size-5" />
              </button>
            </Dialog.Close>
            <Sidebar
              onNavigate={() => {
                setOpen(false);
              }}
            />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <span className="font-semibold">{PRODUCT_NAME}</span>
      <span className="ml-auto text-sm font-semibold">Staging</span>
    </header>
  );
}
