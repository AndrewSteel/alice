import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/Auth/AuthProvider";
import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "Alice",
  description: "Dein persönlicher KI-Assistent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de" suppressHydrationWarning>
      <body className="antialiased">
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
