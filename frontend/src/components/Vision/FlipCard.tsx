"use client";

import { useState } from "react";
import type { VisionResult } from "@/services/api";
import { ThumbnailImage } from "./ThumbnailImage";
import { Sigma } from "lucide-react";
import { Button } from "@/components/ui/button";

export type CardFace = "front" | "back" | "summary";

interface FlipCardProps {
  result: VisionResult;
  /** Controlled face — when undefined, card manages its own state. */
  face?: CardFace;
  onFaceChange?: (face: CardFace) => void;
}

// ISO date/datetime → German dd.MM.yyyy; everything else passes through.
function formatMetaValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/^\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:?\d{2})?)?$/.test(s)) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString("de-DE", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      });
    }
  }
  return s;
}

// German labels for metadata keys that fall outside the doc-type label map.
const EXTRA_META_LABELS: Record<string, string> = {
  date: "Datum",
  amount: "Betrag",
  totalAmount: "Betrag",
  sender: "Absender",
  issuer: "Aussteller",
  subject: "Betreff",
  emailSubject: "Betreff",
  fromAddress: "Von",
  iban: "IBAN",
  counterparty: "Gegenseite",
  bankName: "Bank",
};

// Technical/search fields that must never appear on the detail face.
const HIDDEN_META_KEYS = new Set([
  "score",
  "distance",
  "certainty",
  "weaviate_id",
  "weaviate_uuid",
  "id",
  "uuid",
  "collection",
  "document_type",
  "filename",
]);

function MetadataRow({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex justify-between gap-2 text-xs text-gray-300 py-0.5">
      <span className="text-gray-500 shrink-0">{label}</span>
      <span className="text-right truncate">{formatMetaValue(value)}</span>
    </div>
  );
}

const DOC_META_LABELS: Record<string, Record<string, string>> = {
  Invoice: { invoiceDate: "Datum", totalAmount: "Betrag", issuer: "Aussteller" },
  BankStatement: { statementDate: "Datum", bankName: "Bank", accountIban: "IBAN" },
  BankTransaction: { transactionDate: "Datum", amount: "Betrag", counterparty: "Gegenseite", direction: "Art" },
  Email: { sentAt: "Gesendet", fromAddress: "Von", emailSubject: "Betreff" },
  Document: { date: "Datum", sender: "Absender" },
  SecuritySettlement: { date: "Datum", amount: "Betrag" },
  Contract: { date: "Datum", sender: "Partner" },
};

export function FlipCard({ result, face: faceProp, onFaceChange }: FlipCardProps) {
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
  const metaLabels = DOC_META_LABELS[result.document_type] ?? DOC_META_LABELS["Document"];

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
          className="relative flex flex-col bg-gray-800 border border-gray-700 rounded-lg overflow-hidden cursor-pointer"
          style={{ backfaceVisibility: "hidden" }}
          onClick={() => setFace("back")}
        >
          {/* Filename header */}
          <div className="px-2 py-1.5 bg-gray-900 border-b border-gray-700">
            <p className="text-xs text-gray-300 font-medium truncate" title={result.filename}>
              {result.filename || "Unbekannt"}
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
          <div className="px-2 py-1 bg-gray-850 border-t border-gray-700 text-xs text-gray-400 truncate">
            {Object.entries(metaLabels)
              .filter(([k]) => result.metadata[k])
              .slice(0, 2)
              .map(([k, label]) => (
                <span key={k} className="mr-2">
                  <span className="text-gray-600">{label}: </span>
                  {formatMetaValue(result.metadata[k])}
                </span>
              ))}
            {!Object.keys(metaLabels).some((k) => result.metadata[k]) && (
              <span className="text-gray-600">{result.document_type}</span>
            )}
          </div>

          {/* Icon bar */}
          <div
            className="flex items-center gap-1 px-2 py-1 bg-gray-900 border-t border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-gray-400 hover:text-gray-100"
              title="Zusammenfassung"
              onClick={() => setFace("summary")}
            >
              <Sigma className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* ── Back face (and Summary) — shown when flipped ── */}
        <div
          className="absolute inset-0 flex flex-col bg-gray-800 border border-gray-700 rounded-lg overflow-hidden cursor-pointer"
          style={{
            backfaceVisibility: "hidden",
            transform: "rotateY(180deg)",
          }}
          onClick={() => setFace("front")}
        >
          {face === "summary" ? (
            <>
              <div className="px-2 py-1.5 bg-gray-900 border-b border-gray-700">
                <p className="text-xs text-gray-400 font-medium">Zusammenfassung</p>
              </div>
              <div className="flex-1 overflow-y-auto p-3">
                {result.summary ? (
                  <p className="text-xs text-gray-300 leading-relaxed">{result.summary}</p>
                ) : (
                  <p className="text-xs text-gray-600 italic">Keine Zusammenfassung verfügbar.</p>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="px-2 py-1.5 bg-gray-900 border-b border-gray-700">
                <p className="text-xs text-gray-400 font-medium">Details</p>
              </div>
              <div className="flex-1 overflow-y-auto p-3 space-y-0.5">
                <MetadataRow label="Typ" value={result.document_type} />
                <MetadataRow label="Datei" value={result.filename} />
                {Object.entries(metaLabels).map(([k, label]) => (
                  <MetadataRow key={k} label={label} value={result.metadata[k]} />
                ))}
                {/* Extra metadata fields not in the labels map — German
                    labels where known, technical/search fields hidden. */}
                {Object.entries(result.metadata)
                  .filter(
                    ([k, v]) =>
                      !metaLabels[k] &&
                      !HIDDEN_META_KEYS.has(k) &&
                      v !== null &&
                      v !== undefined &&
                      v !== ""
                  )
                  .slice(0, 6)
                  .map(([k, v]) => (
                    <MetadataRow key={k} label={EXTRA_META_LABELS[k] ?? k} value={v} />
                  ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
