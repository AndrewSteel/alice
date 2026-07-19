import { LayoutGrid } from "lucide-react";

export function VisionEmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-6 py-12">
      <LayoutGrid className="w-12 h-12 text-muted-foreground mb-4" />
      <p className="text-muted-foreground text-sm">Keine Treffer gefunden</p>
    </div>
  );
}
