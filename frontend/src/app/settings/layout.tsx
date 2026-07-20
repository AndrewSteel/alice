import { ProtectedRoute } from "@/components/Auth/ProtectedRoute";
import { SettingsShell } from "@/components/Settings/SettingsShell";

/**
 * Shared layout for all Settings subroutes (PROJ-68). Auth-guards once and
 * renders the persistent Settings shell (header + tab bar). The shell stays
 * mounted across tab navigation, so `usePermissions()` fetches a single time.
 */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <SettingsShell>{children}</SettingsShell>
    </ProtectedRoute>
  );
}
