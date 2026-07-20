"use client";

import { useState, useRef } from "react";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const MAX_TAGS = 20;
const MAX_TAG_LENGTH = 30;

interface InteressenTagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
}

export function InteressenTagInput({ tags, onChange }: InteressenTagInputProps) {
  const { t } = useTranslation();
  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const isAtLimit = tags.length >= MAX_TAGS;

  function addTag(value: string) {
    const trimmed = value.trim();
    if (!trimmed) return;
    if (trimmed.length > MAX_TAG_LENGTH) return;

    // Case-insensitive duplicate check
    const isDuplicate = tags.some(
      (t) => t.toLowerCase() === trimmed.toLowerCase()
    );
    if (isDuplicate) {
      setInputValue("");
      return;
    }

    if (isAtLimit) return;

    onChange([...tags, trimmed]);
    setInputValue("");
  }

  function removeTag(index: number) {
    const next = tags.filter((_, i) => i !== index);
    onChange(next);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addTag(inputValue);
    }
    // Allow backspace to remove last tag when input is empty
    if (e.key === "Backspace" && !inputValue && tags.length > 0) {
      removeTag(tags.length - 1);
    }
  }

  return (
    <div className="space-y-2">
      {/* Tags display */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-2" role="list" aria-label={t("settings.interests.listLabel")}>
          {tags.map((tag, index) => (
            <Badge
              key={`${tag}-${index}`}
              variant="secondary"
              className="bg-muted text-foreground border-border gap-1 pr-1"
              role="listitem"
            >
              {tag}
              <button
                type="button"
                onClick={() => removeTag(index)}
                className="ml-1 rounded-full p-0.5 hover:bg-accent focus:outline-none focus:ring-1 focus:ring-ring"
                aria-label={t("settings.interests.removeAria", { tag })}
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* Input field */}
      <div className="flex gap-2">
        <Input
          ref={inputRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={isAtLimit ? t("settings.interests.maxReached") : t("settings.interests.placeholder")}
          maxLength={MAX_TAG_LENGTH}
          disabled={isAtLimit}
          className="bg-card border-border text-foreground placeholder:text-muted-foreground"
          aria-label={t("settings.interests.ariaLabel")}
        />
      </div>

      {/* Hint */}
      {isAtLimit && (
        <p className="text-xs text-amber-400">{t("settings.interests.maxReached")}</p>
      )}
    </div>
  );
}
