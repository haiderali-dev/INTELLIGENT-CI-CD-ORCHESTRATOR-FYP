import { PRODUCT_NAME } from "@/app/shell/nav";

/**
 * Shown on the first load while the page asked for arrives: pages are loaded on demand
 * (src/app/routes.tsx), and React Router draws nothing until the first one is there. Static text,
 * like RestoringSession: DESIGN.md section 7 allows only the running icon to loop.
 */
export function LoadingApp() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-ground px-4 text-ink">
      <title>{PRODUCT_NAME}</title>
      <p role="status" className="text-base text-graphite">
        Loading
      </p>
    </div>
  );
}
