import { Link } from "react-router";

import { AuditSection } from "@/admin/AuditSection";
import { PolicySection } from "@/admin/PolicySection";
import { UsersSection } from "@/admin/UsersSection";
import type { NavItem } from "@/app/shell/nav";
import { isAdmin, ROLE_LABEL } from "@/auth/roles";
import { useSignedInUser } from "@/auth/sessionContext";
import { PageHeader } from "@/components/PageHeader";
import { Empty } from "@/components/PageStates";

/**
 * Admin (4.7.3): users and roles, the HIGH quota and the rules in force, and the audit log. Only an
 * Admin is shown it in the sidebar. Anyone else who opens it is told why it is closed to them, and
 * the page asks the backend for nothing it would refuse.
 */
export function AdminPage({ item }: { item: Pick<NavItem, "label" | "description"> }) {
  const user = useSignedInUser();

  if (!user || !isAdmin(user)) {
    return (
      <>
        <PageHeader title={item.label} description={item.description} />
        <div className="py-6">
          <Empty>
            <p className="font-semibold">Only Admins can use this page.</p>
            <p>
              {`${user ? `Your role is ${ROLE_LABEL[user.role]}. ` : ""}To change a role, add someone or read the audit log, ask an Admin.`}
            </p>
            <p>
              <Link to="/" className="font-semibold underline underline-offset-4">
                Go to the Overview
              </Link>
            </p>
          </Empty>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={item.label} description={item.description} />
      <UsersSection me={user.id} />
      <PolicySection />
      <AuditSection />
    </>
  );
}
