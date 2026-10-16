import { NavLink } from "react-router";

import { isAdmin } from "@/auth/roles";
import { useSignedInUser } from "@/auth/sessionContext";
import { cn } from "@/lib/cn";

import { ACCENT_TEXT, NAV_ITEMS, PRODUCT_NAME } from "./nav";
import { SignedInAs } from "./SignedInAs";
import { ThemeSwitch } from "./ThemeSwitch";

/** Every page by name, the assistants as separate entries in their own colours, and a footer that
 * says Staging and who is signed in (DESIGN.md section 4, Shell). */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  // An entry that could only end in a refusal is a dead end (4.7.3), so Admin is listed for Admins.
  const admin = isAdmin(useSignedInUser());
  const items = NAV_ITEMS.filter(({ adminOnly }) => !adminOnly || admin);
  return (
    <div className="flex h-full flex-col gap-6 bg-ground px-3 py-4">
      <p className="px-3 text-base font-semibold">{PRODUCT_NAME}</p>

      <nav aria-label="Main">
        <ul className="flex flex-col gap-1">
          {items.map(({ to, label, icon: Icon, accent }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === "/"}
                onClick={onNavigate}
                className={({ isActive }) =>
                  cn(
                    "relative flex items-center gap-3 rounded-control px-3 py-2 text-base",
                    "hover:bg-panel",
                    isActive &&
                      "bg-panel font-semibold before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:bg-ink",
                  )
                }
              >
                <Icon
                  aria-hidden="true"
                  className={cn("size-5 shrink-0", accent ? ACCENT_TEXT[accent] : "text-graphite")}
                />
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-auto flex flex-col gap-4 border-t border-rule px-3 pt-4">
        <p className="text-sm">
          <span className="text-graphite">Environment </span>
          <span className="font-semibold">Staging</span>
        </p>
        <SignedInAs />
        <ThemeSwitch />
      </div>
    </div>
  );
}
