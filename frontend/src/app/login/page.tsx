"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { decodeJwt } from "jose";
import { getToken } from "@/services/auth";
import { LoginForm } from "@/components/Auth/LoginForm";

export default function LoginPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (token) {
      try {
        const payload = decodeJwt(token);
        const exp = payload.exp as number;
        if (exp && Date.now() / 1000 < exp) {
          // Token still valid -- redirect to home
          router.replace("/");
          return;
        }
      } catch {
        // Invalid token -- stay on login page
      }
    }
    setReady(true);
  }, [router]);

  if (!ready) return null;

  return (
    <main className="min-h-screen bg-gray-900 flex items-start justify-center md:items-center p-6">
      {/* Mobile: vollflächig, Tablet+: zentrierte Card */}
      <div className="w-full max-w-sm md:bg-gray-800 md:rounded-xl md:shadow-xl md:p-8 pt-12 md:pt-8">
        <LoginForm />
      </div>
    </main>
  );
}
