"use client";

import { useState, useRef } from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const MAX_TAGS = 20;
const MAX_TAG_LENGTH = 30;

interface InteressenTagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
}

export function InteressenTagInput({ tags, onChange }: InteressenTagInputProps) {
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
        <div className="flex flex-wrap gap-2" role="list" aria-label="Interessen">
          {tags.map((tag, index) => (
            <Badge
              key={`${tag}-${index}`}
              variant="secondary"
              className="bg-gray-700 text-gray-200 border-gray-600 gap-1 pr-1"
              role="listitem"
            >
              {tag}
              <button
                type="button"
                onClick={() => removeTag(index)}
                className="ml-1 rounded-full p-0.5 hover:bg-gray-600 focus:outline-none focus:ring-1 focus:ring-gray-500"
                aria-label={`${tag} entfernen`}
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
          placeholder={isAtLimit ? "Maximum erreicht (20 Tags)" : "Interesse eingeben + Enter"}
          maxLength={MAX_TAG_LENGTH}
          disabled={isAtLimit}
          className="bg-gray-800 border-gray-600 text-gray-100 placeholder:text-gray-500"
          aria-label="Neues Interesse eingeben"
        />
      </div>

      {/* Hint */}
      {isAtLimit && (
        <p className="text-xs text-amber-400">Maximum erreicht (20 Tags)</p>
      )}
    </div>
  );
}
