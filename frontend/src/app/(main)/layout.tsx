"use client";

import { useEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/Auth/ProtectedRoute";
import { useAuth } from "@/hooks/useAuth";
import { ChatSessionsProvider } from "@/components/Chat/ChatSessionsProvider";

/**
 * Decides the landing page once per full page load (PROJ-77 AC-A1/A3/A7):
 * admins land on /dashboard, everyone else on / (Chat). Runs only on mount —
 * this layout persists across client-side navigation between "/" and
 * "/dashboard" (the Nutzermenü "Dashboard"/"Chat" items), so a deliberate
 * switch between the two views is never overridden — only a fresh page
 * load/reload re-decides (AC-A4/A5 vs AC-A1/A7).
 *
 * `children` is withheld until that one-time decision has fired (mirrors the
 * route-guard pattern already used by SettingsShell/PROJ-68) — otherwise the
 * about-to-be-redirected-away-from page mounts for one render: a non-admin
 * hitting /dashboard directly would briefly fire the admin-only tile
 * fetches, and an admin landing on "/" would briefly mount the Chat page,
 * whose effect auto-creates an empty session before the redirect lands
 * (leaving a phantom "Neuer Chat" behind in the sidebar every single load).
 */
function LandingRedirect({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  // Set once the redirect check has actually run — read (not written) during
  // render, so it doesn't need to trigger a re-render itself; the eventual
  // pathname change from router.replace() does that for us.
  const firedRef = useRef(false);

  const mismatched =
    !!user &&
    ((user.role === "admin" && pathname === "/") ||
      (user.role !== "admin" && pathname === "/dashboard"));

  useEffect(() => {
    if (firedRef.current || !user) return;
    firedRef.current = true;
    if (mismatched) {
      router.replace(user.role === "admin" ? "/dashboard" : "/");
    }
    // Intentionally empty deps — this must fire exactly once per mount
    // (= once per full page load), not on every client-side navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Block only up until the one-time check has run — afterwards, even a
  // pathname that's structurally "mismatched" (e.g. an admin who
  // deliberately navigated to "/" via the Nutzermenü) renders normally.
  if (mismatched && !firedRef.current) return null;
  return <>{children}</>;
}

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <ChatSessionsProvider>
        <LandingRedirect>{children}</LandingRedirect>
      </ChatSessionsProvider>
    </ProtectedRoute>
  );
}
