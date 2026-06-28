"use client";

import { useState } from "react";
import type { VisionResult } from "@/services/api";
import { FlipCard, type CardFace } from "./FlipCard";

interface FlipCardGridProps {
  results: VisionResult[];
}

export function FlipCardGrid({ results }: FlipCardGridProps) {
  // Track the active face per card (keyed by uuid)
  const [faces, setFaces] = useState<Record<string, CardFace>>({});

  const setFace = (uuid: string, face: CardFace) => {
    setFaces((prev) => ({ ...prev, [uuid]: face }));
  };

  return (
    <div
      className={`
        grid gap-3 p-3
        grid-cols-2
        sm:grid-cols-4
        md:grid-cols-[repeat(auto-fill,minmax(200px,1fr))]
      `}
    >
      {results.map((result) => (
        <FlipCard
          key={result.uuid}
          result={result}
          face={faces[result.uuid] ?? "front"}
          onFaceChange={(face) => setFace(result.uuid, face)}
        />
      ))}
    </div>
  );
}
