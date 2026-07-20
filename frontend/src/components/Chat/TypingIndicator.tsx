"use client";

import { useTranslation } from "react-i18next";

export function TypingIndicator() {
  const { t } = useTranslation();
  return (
    <div className="flex items-start gap-3 px-4 py-2" aria-label={t("chat.typing.label")}>
      <div className="flex items-center gap-1.5 rounded-2xl bg-muted px-4 py-3">
        <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:0ms]" />
        <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:150ms]" />
        <span className="h-2 w-2 rounded-full bg-muted-foreground animate-bounce [animation-delay:300ms]" />
        <span className="sr-only">{t("chat.typing.sr")}</span>
      </div>
    </div>
  );
}
