"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/hooks/useAuth";

export function AllgemeinSection() {
  const { t } = useTranslation();
  const { user } = useAuth();

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-foreground">{t("settings.allgemein.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div>
            <p className="text-sm text-muted-foreground">{t("settings.allgemein.loggedInAs")}</p>
            <p className="text-foreground font-medium">{user?.username}</p>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">{t("settings.allgemein.role")}</p>
            <p className="text-foreground font-medium capitalize">{user?.role}</p>
          </div>
          <p className="text-sm text-muted-foreground pt-2">
            {t("settings.allgemein.moreSoon")}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
