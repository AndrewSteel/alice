import { ProtectedRoute } from "@/components/Auth/ProtectedRoute";
import { AppShell } from "@/components/Layout/AppShell";

export default function Home() {
  return (
    <ProtectedRoute>
      <AppShell />
    </ProtectedRoute>
  );
}
