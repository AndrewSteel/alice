"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";

export function AllgemeinSection() {
  const { user } = useAuth();

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-foreground">Allgemein</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div>
            <p className="text-sm text-muted-foreground">Angemeldet als</p>
            <p className="text-foreground font-medium">{user?.username}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">Rolle</p>
            <p className="text-foreground font-medium capitalize">{user?.role}</p>
          </div>
          <p className="text-sm text-muted-foreground pt-2">
            Weitere Einstellungen folgen in einem spaeteren Update.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
