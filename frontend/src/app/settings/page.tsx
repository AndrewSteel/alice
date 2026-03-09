import { ProtectedRoute } from "@/components/Auth/ProtectedRoute";
import { SettingsPage } from "@/components/Settings/SettingsPage";

export default function Settings() {
  return (
    <ProtectedRoute>
      <SettingsPage />
    </ProtectedRoute>
  );
}
