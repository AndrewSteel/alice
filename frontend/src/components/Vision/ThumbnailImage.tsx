"use client";

import { useEffect, useRef, useState } from "react";
import { getToken } from "@/services/auth";
import { Skeleton } from "@/components/ui/skeleton";
import { FileText } from "lucide-react";

interface ThumbnailImageProps {
  uuid: string;
  alt: string;
  className?: string;
}

export function ThumbnailImage({ uuid, alt, className = "" }: ThumbnailImageProps) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const token = getToken();
      if (!token) return;

      try {
        const res = await fetch(`/api/dms/thumbnail/${encodeURIComponent(uuid)}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (cancelled) return;
        if (!res.ok) {
          if (!cancelled) setError(true);
          return;
        }
        const blob = await res.blob();
        if (cancelled) return;
        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;
        setSrc(url);
      } catch {
        if (!cancelled) setError(true);
      }
    }

    load();

    return () => {
      cancelled = true;
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [uuid]);

  if (error) {
    return (
      <div className={`flex items-center justify-center bg-muted ${className}`}>
        <FileText className="w-12 h-12 text-muted-foreground" />
      </div>
    );
  }

  if (!src) {
    return <Skeleton className={`bg-muted ${className}`} />;
  }

  return (
    <img
      src={src}
      alt={alt}
      className={`object-cover ${className}`}
      draggable={false}
    />
  );
}
