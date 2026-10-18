import RequireLogin from "@/components/RequireLogin";

// Signed-in-only route (QA round 2 #1): logged-out visitors are redirected
// to /login?next=<this page> instead of seeing an empty app shell.
export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return <RequireLogin>{children}</RequireLogin>;
}
