import { PRODUCT_NAME } from "@/app/shell/nav";

/** Shown for the moment it takes to trade a stored refresh token for a session after a reload.
 * Static text, not a spinner: DESIGN.md section 7 allows only the running icon to loop. */
export function RestoringSession() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-ground px-4 text-ink">
      <title>{PRODUCT_NAME}</title>
      <p role="status" className="text-base text-graphite">
        Restoring your session
      </p>
    </div>
  );
}
