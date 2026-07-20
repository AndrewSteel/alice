import { Skeleton } from "@/components/ui/skeleton";

/**
 * Placeholder shown in the Settings content area while a route's Section chunk
 * is being loaded (dynamic import) or while a guard redirect is in flight.
 * Deliberately generic — it stands in for any of the section panels.
 */
export function SettingsSectionSkeleton() {
  return (
    <div className="space-y-4" aria-hidden="true">
      <Skeleton className="h-7 w-40 bg-muted" />
      <Skeleton className="h-24 w-full bg-muted" />
      <Skeleton className="h-24 w-full bg-muted" />
    </div>
  );
}
