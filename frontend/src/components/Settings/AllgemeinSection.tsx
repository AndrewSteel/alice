"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";

export function AllgemeinSection() {
  const { user } = useAuth();

  return (
    <Card className="bg-gray-800 border-gray-700">
      <CardHeader>
        <CardTitle className="text-gray-100">Allgemein</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div>
            <p className="text-sm text-gray-400">Angemeldet als</p>
            <p className="text-gray-100 font-medium">{user?.username}</p>
          </div>
          <div>
            <p className="text-sm text-gray-400">Rolle</p>
            <p className="text-gray-100 font-medium capitalize">{user?.role}</p>
          </div>
          <p className="text-sm text-gray-500 pt-2">
            Weitere Einstellungen folgen in einem spaeteren Update.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
