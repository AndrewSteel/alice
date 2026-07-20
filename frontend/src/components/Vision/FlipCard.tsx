"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { VisionResult } from "@/services/api";
import { ThumbnailImage } from "./ThumbnailImage";
import { formatMetaValue } from "@/i18n/format";
import { Sigma } from "lucide-react";
import { Button } from "@/components/ui/button";

export type CardFace = "front" | "back" | "summary";

interface FlipCardProps {
  result: VisionResult;
  /** Controlled face — when undefined, card manages its own state. */
  face?: CardFace;
  onFaceChange?: (face: CardFace) => void;
}

function MetadataRow({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-2 text-sm text-foreground py-0.5">
      <span className="text-muted-foreground shrink-0">{label}</span>
      <span className="text-right truncate">{formatMetaValue(value)}</span>
    </div>
  );
}

export function FlipCard({ result, face: faceProp, onFaceChange }: FlipCardProps) {
  const { t } = useTranslation();
  const [internalFace, setInternalFace] = useState<CardFace>("front");
  const face = faceProp ?? internalFace;

  const setFace = (f: CardFace) => {
    if (onFaceChange) {
      onFaceChange(f);
    } else {
      setInternalFace(f);
    }
  };

  const isFlipped = face !== "front";

  // Data-driven metadata labels (PROJ-62): the former hardcoded German maps now
  // live in the translation resource under `vision.docMeta` / `vision.extraMeta`
  // / `vision.hiddenMetaKeys` and follow the active UI language.
  const docMetaRaw = t(`vision.docMeta.${result.document_type}`, {
    returnObjects: true,
    defaultValue: {},
  });
  const fallbackMeta = t("vision.docMeta.Document", {
    returnObjects: true,
    defaultValue: {},
  }) as Record<string, string>;
  const metaLabels =
    docMetaRaw && typeof docMetaRaw === "object" && Object.keys(docMetaRaw).length > 0
      ? (docMetaRaw as Record<string, string>)
      : fallbackMeta;
  const hiddenMetaKeys = new Set(
    t("vision.hiddenMetaKeys", { returnObjects: true, defaultValue: [] }) as string[]
  );

  return (
    <div
      className="relative w-full"
      style={{ perspective: "800px" }}
    >
      {/* Card container — 3D flip. The front face sits in normal flow and
          defines the card height; the back face overlays it absolutely. */}
      <div
        className="relative w-full transition-transform duration-500"
        style={{
          transformStyle: "preserve-3d",
          transform: isFlipped ? "rotateY(180deg)" : "rotateY(0deg)",
        }}
      >
        {/* ── Front face ── */}
        <div
          className="relative flex flex-col bg-card border border-border rounded-lg overflow-hidden cursor-pointer"
          style={{ backfaceVisibility: "hidden" }}
          onClick={() => setFace("back")}
        >
          {/* Filename header */}
          <div className="px-2 py-1.5 bg-background border-b border-border">
            <p className="text-sm lg:text-base text-foreground font-medium truncate" title={result.filename}>
              {result.filename || t("vision.card.unknownFile")}
            </p>
          </div>

          {/* Thumbnail — strict 1:1 square preview */}
          <div className="aspect-square w-full overflow-hidden">
            <ThumbnailImage
              uuid={result.uuid}
              alt={result.filename}
              className="w-full h-full"
            />
          </div>

          {/* Metadata bar */}
          <div className="px-2 py-1 bg-card border-t border-border text-xs sm:text-sm text-muted-foreground truncate">
            {Object.entries(metaLabels)
              .filter(([k]) => result.metadata[k])
              .slice(0, 2)
              .map(([k, label]) => (
                <span key={k} className="mr-2">
                  <span className="text-muted-foreground">{label}: </span>
                  {formatMetaValue(result.metadata[k])}
                </span>
              ))}
            {!Object.keys(metaLabels).some((k) => result.metadata[k]) && (
              <span className="text-muted-foreground">{result.document_type}</span>
            )}
          </div>

          {/* Icon bar */}
          <div
            className="flex items-center gap-1 px-2 py-1 bg-background border-t border-border"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              variant="ghost"
              size="icon"
              className="h-11 w-11 text-muted-foreground hover:text-foreground"
              title={t("vision.card.summary")}
              onClick={() => setFace("summary")}
            >
              <Sigma className="h-5 w-5" />
            </Button>
          </div>
        </div>

        {/* ── Back face (and Summary) — shown when flipped ── */}
        <div
          className="absolute inset-0 flex flex-col bg-card border border-border rounded-lg overflow-hidden cursor-pointer"
          style={{
            backfaceVisibility: "hidden",
            transform: "rotateY(180deg)",
          }}
          onClick={() => setFace("front")}
        >
          {face === "summary" ? (
            <>
              <div className="px-2 py-1.5 bg-background border-b border-border">
                <p className="text-sm text-muted-foreground font-medium">{t("vision.card.summary")}</p>
              </div>
              <div className="flex-1 overflow-y-auto p-3">
                {result.summary ? (
                  <p className="text-sm lg:text-base text-foreground leading-relaxed">{result.summary}</p>
                ) : (
                  <p className="text-sm text-muted-foreground italic">{t("vision.card.noSummary")}</p>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="px-2 py-1.5 bg-background border-b border-border">
                <p className="text-sm text-muted-foreground font-medium">{t("vision.card.details")}</p>
              </div>
              <div className="flex-1 overflow-y-auto p-3 space-y-0.5">
                <MetadataRow label={t("vision.card.typeLabel")} value={result.document_type} />
                <MetadataRow label={t("vision.card.fileLabel")} value={result.filename} />
                {Object.entries(metaLabels).map(([k, label]) => (
                  <MetadataRow key={k} label={label} value={result.metadata[k]} />
                ))}
                {/* Extra metadata fields not in the labels map — translated
                    labels where known, technical/search fields hidden. */}
                {Object.entries(result.metadata)
                  .filter(
                    ([k, v]) =>
                      !metaLabels[k] &&
                      !hiddenMetaKeys.has(k) &&
                      v !== null &&
                      v !== undefined &&
                      v !== ""
                  )
                  .slice(0, 6)
                  .map(([k, v]) => (
                    <MetadataRow key={k} label={t(`vision.extraMeta.${k}`, { defaultValue: k })} value={v} />
                  ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
