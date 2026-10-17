import { Link } from "react-router";

import { PageHeader } from "@/components/PageHeader";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" description="Nothing lives at this address." />
      <div className="px-6 py-6">
        <Link to="/" className="font-semibold underline underline-offset-4">
          Go to the overview
        </Link>
      </div>
    </>
  );
}
