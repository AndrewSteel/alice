"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";

interface ChatSearchProps {
  value: string;
  onChange: (v: string) => void;
}

export function ChatSearch({ value, onChange }: ChatSearchProps) {
  return (
    <div className="relative px-2">
      <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-500 pointer-events-none" />
      <Input
        type="search"
        placeholder="Suche"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="pl-8 h-8 bg-gray-700 border-gray-600 text-gray-100 placeholder:text-gray-500 text-sm focus:border-blue-500"
        aria-label="Chats durchsuchen"
      />
    </div>
  );
}
