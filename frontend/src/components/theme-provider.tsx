"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * App-wide theme provider (next-themes).
 *
 * - No persisted preference by default -> follows `prefers-color-scheme`.
 * - A manual choice is stored in localStorage (key "theme") and overrides
 *   the system preference on future visits.
 * - Choosing "system" clears the override and live-follows OS changes.
 * - Injects a blocking script before hydration to avoid FOUC.
 * - localStorage access is wrapped internally; a blocked storage degrades
 *   gracefully to the system preference on every load.
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}
