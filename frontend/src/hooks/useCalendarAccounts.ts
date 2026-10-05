import { useCallback, useEffect, useState } from "react";
import {
  getCalendarAccounts,
  updateCalendarSelection,
  type CalendarAccount,
  type CalendarSelection,
} from "@/services/calendar";

/**
 * PROJ-87 — Google accounts + live calendar lists for the "Kalender" tab.
 * Selection toggles are applied from the server's authoritative answer, so the
 * auto-default / default-removal rules always show exactly what was stored.
 */
export function useCalendarAccounts() {
  const [accounts, setAccounts] = useState<CalendarAccount[]>([]);
  const [requiredScopes, setRequiredScopes] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    setError(null);
    try {
      const data = await getCalendarAccounts();
      setAccounts(data.accounts);
      setRequiredScopes(data.required_scopes);
    } catch (err) {
      setError(err);
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  function applySelections(selections: CalendarSelection[]) {
    const key = (c: string, id: string) => `${c}\u0000${id}`;
    const byKey = new Map(selections.map((s) => [key(s.connection_id, s.calendar_id), s]));
    setAccounts((prev) =>
      prev.map((acc) => ({
        ...acc,
        calendars: acc.calendars?.map((cal) => {
          const sel = byKey.get(key(acc.connection_id, cal.id));
          return { ...cal, is_active: !!sel?.is_active, is_default: !!sel?.is_default };
        }) ?? null,
      }))
    );
  }

  async function setActive(connectionId: string, calendarId: string, isActive: boolean) {
    applySelections(await updateCalendarSelection({
      connection_id: connectionId, calendar_id: calendarId, is_active: isActive,
    }));
  }

  async function setDefault(connectionId: string, calendarId: string) {
    applySelections(await updateCalendarSelection({
      connection_id: connectionId, calendar_id: calendarId, is_default: true,
    }));
  }

  return { accounts, requiredScopes, isLoading, error, reload: load, setActive, setDefault };
}
