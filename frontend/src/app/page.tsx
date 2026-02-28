import { ProtectedRoute } from "@/components/Auth/ProtectedRoute";
import { AppShell } from "@/components/Layout/AppShell";

export default function Home() {
  return (
    <ProtectedRoute>
      <AppShell>
        {/* Chat-Inhalt kommt in PROJ-8 */}
        <div className="flex items-center justify-center h-full text-gray-500">
          <p>Wähle einen Chat oder starte einen neuen.</p>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
