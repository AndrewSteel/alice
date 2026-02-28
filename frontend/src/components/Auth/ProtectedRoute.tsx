"use client";

import { useAuth } from "@/hooks/useAuth";
import { Skeleton } from "@/components/ui/skeleton";

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-900">
        <div className="space-y-3 w-64">
          <Skeleton className="h-8 w-full bg-gray-700" />
          <Skeleton className="h-8 w-3/4 bg-gray-700" />
          <Skeleton className="h-8 w-1/2 bg-gray-700" />
        </div>
      </div>
    );
  }

  if (!user) {
    // Router-Redirect läuft bereits im AuthProvider
    return null;
  }

  return <>{children}</>;
}
