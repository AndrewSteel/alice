"use client";

import ReactMarkdown, { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";
import { Message } from "../types";

interface AssistantMessageProps {
  message: Message;
}

// Inline code vs. code block: rehype-highlight handles the highlight classes
// inside `<code class="language-…">`. We only style the wrappers here.
const markdownComponents: Components = {
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return (
        <code className={cn("hljs", className)} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code
        className="bg-gray-800 text-pink-300 rounded px-1 py-0.5 text-[13px] font-mono"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="not-prose my-3 rounded-md bg-gray-950 border border-gray-700 p-3 text-[13px] font-mono overflow-x-auto">
      {children}
    </pre>
  ),
  a: ({ children, ...props }) => (
    <a target="_blank" rel="noopener noreferrer" {...props}>
      {children}
    </a>
  ),
};

export function AssistantMessage({ message }: AssistantMessageProps) {
  const { content, streaming } = message;

  return (
    <div className="px-4 py-3 min-w-0">
      <div
        className={cn(
          "prose prose-invert max-w-none min-w-0 break-words [overflow-wrap:anywhere]",
          // Base typography (16px / gray-200)
          "text-[16px] text-gray-200 leading-relaxed",
          "prose-p:text-[16px] prose-p:text-gray-200 prose-p:my-2 prose-p:leading-relaxed",
          // Headings
          "prose-headings:text-gray-100 prose-headings:font-semibold",
          "prose-h1:text-[22px] prose-h2:text-[19px] prose-h3:text-[17px] prose-h4:text-[16px]",
          // Strong / em
          "prose-strong:font-semibold prose-strong:text-gray-100",
          "prose-em:italic",
          // Links
          "prose-a:text-blue-400 hover:prose-a:text-blue-300 prose-a:underline-offset-2",
          // Blockquotes / hr / lists
          "prose-blockquote:border-gray-600 prose-blockquote:text-gray-300",
          "prose-hr:border-gray-700",
          "prose-ul:my-2 prose-ol:my-2 prose-li:my-1",
          // Tables (gfm)
          "prose-table:text-sm",
          "prose-th:border prose-th:border-gray-700 prose-th:px-2 prose-th:py-1",
          "prose-td:border prose-td:border-gray-700 prose-td:px-2 prose-td:py-1",
          // Streaming caret
          streaming &&
            "after:content-[''] after:inline-block after:w-[2px] after:h-[1em] after:bg-gray-300 after:ml-0.5 after:align-text-bottom after:animate-pulse"
        )}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
          components={markdownComponents}
        >
          {content || ""}
        </ReactMarkdown>
      </div>
    </div>
  );
}
