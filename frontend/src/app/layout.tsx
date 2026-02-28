import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/Auth/AuthProvider";

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
    <html lang="de" className="dark">
      <body className="antialiased bg-gray-900 text-gray-100">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
