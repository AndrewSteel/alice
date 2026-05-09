"use client";

import { AlertCircle } from "lucide-react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  role: "user" | "assistant" | "error";
  content: string;
  streaming?: boolean;
}

// Keep inline vs block code distinct; everything else is handled by prose.
const markdownComponents: Components = {
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return (
        <code
          className={cn(
            "block bg-gray-950 border border-gray-700 rounded-md p-3 my-2 text-xs font-mono overflow-x-auto",
            className
          )}
          {...props}
        >
          {children}
        </code>
      );
    }
    return (
      <code
        className="bg-gray-950/70 text-pink-300 rounded px-1 py-0.5 text-xs font-mono"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => <pre className="not-prose my-2">{children}</pre>,
};

export function MessageBubble({ role, content, streaming = false }: MessageBubbleProps) {
  if (role === "error") {
    return (
      <div className="flex items-start gap-3 px-4 py-2">
        <div className="flex items-start gap-2 rounded-2xl bg-red-900/40 border border-red-700/50 px-4 py-3 max-w-[85%] md:max-w-[70%]">
          <AlertCircle className="h-4 w-4 text-red-400 mt-0.5 shrink-0" />
          <p className="text-sm text-red-300 whitespace-pre-wrap break-words">
            {content}
          </p>
        </div>
      </div>
    );
  }

  const isUser = role === "user";

  return (
    <div
      className={cn(
        "flex px-4 py-2",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[85%] md:max-w-[70%] rounded-2xl px-4 py-3",
          isUser
            ? "bg-gray-600 text-gray-100"
            : "bg-transparent text-gray-200"
        )}
        data-streaming={streaming ? "true" : undefined}
      >
        {isUser ? (
          <p className="text-sm whitespace-pre-wrap break-words">{content}</p>
        ) : (
          <div
            className={cn(
              "prose prose-invert prose-sm max-w-none break-words",
              "prose-p:my-1.5 prose-p:leading-relaxed",
              "prose-headings:text-gray-100 prose-headings:font-semibold",
              "prose-a:text-blue-400 hover:prose-a:text-blue-300",
              "prose-blockquote:border-gray-600 prose-blockquote:text-gray-300",
              "prose-hr:border-gray-700",
              "prose-table:text-xs prose-th:border prose-th:border-gray-700 prose-td:border prose-td:border-gray-700",
              streaming &&
                "after:content-[''] after:inline-block after:w-[2px] after:h-[1em] after:bg-gray-300 after:ml-0.5 after:align-text-bottom after:animate-pulse"
            )}
          >
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {content || ""}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
