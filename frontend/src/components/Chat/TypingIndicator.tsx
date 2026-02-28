"use client";

export function TypingIndicator() {
  return (
    <div className="flex items-start gap-3 px-4 py-2" aria-label="Alice antwortet">
      <div className="flex items-center gap-1.5 rounded-2xl bg-gray-700 px-4 py-3">
        <span className="h-2 w-2 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
        <span className="h-2 w-2 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
        <span className="h-2 w-2 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
        <span className="sr-only">Alice antwortet...</span>
      </div>
    </div>
  );
}
