"use client";

/**
 * useTimerAlarm — PROJ-85 WebApp timer alarm.
 *
 * Timers are created / changed / deleted through the chat; this hook only
 * shows the alarm. It:
 *   - loads the caller's role-scoped active timers from the server
 *     (authoritative source) on mount, on an interval, on tab focus and when
 *     the chat signals a new timer ("alice:timers-changed")
 *   - counts down locally to each timer's absolute `expires_at`
 *   - when a timer's countdown reaches zero while the tab is visible: a toast
 *     (stays until dismissed) + a short chime
 *   - when the tab is brought back to the foreground after an expiry that
 *     happened while it was hidden: a catch-up toast ("… ist vor X abgelaufen"),
 *     as long as it is within the catch-up window
 *
 * Reliable background notification (locked screen / closed tab) is out of
 * scope — that is PROJ-104 (Web Push).
 */

import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import { getActiveTimers, type ActiveTimer } from "@/services/timers";

const POLL_INTERVAL_MS = 30_000;
// A timer that expired while the tab was hidden is still worth a catch-up
// toast if the tab returns within this window (spec "Nachhol-Fenster").
const CATCH_UP_WINDOW_MS = 15 * 60_000;

function playChime() {
  try {
    const Ctx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const now = ctx.currentTime;
    // Two short rising notes.
    [
      { f: 880, t: 0 },
      { f: 1174, t: 0.18 },
    ].forEach(({ f, t }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = f;
      gain.gain.setValueAtTime(0.0001, now + t);
      gain.gain.exponentialRampToValueAtTime(0.25, now + t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + t + 0.35);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + t);
      osc.stop(now + t + 0.4);
    });
    setTimeout(() => ctx.close().catch(() => {}), 1200);
  } catch {
    // Autoplay policy / no audio device — silent, the toast still shows.
  }
}

function formatAgo(ms: number, t: TFunction): string {
  const secs = Math.round(ms / 1000);
  if (secs < 60) return t("timerAlarm.agoSeconds", { count: secs });
  const mins = Math.round(secs / 60);
  return t("timerAlarm.agoMinutes", { count: mins });
}

export function useTimerAlarm() {
  const { user } = useAuth();
  const { toast } = useToast();
  const { t } = useTranslation();

  // Timers we have already alarmed / caught up on, by id.
  const handledRef = useRef<Set<string>>(new Set());
  // Per-timer countdown timeout handles.
  const timeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const timersRef = useRef<ActiveTimer[]>([]);

  const clearTimeouts = useCallback(() => {
    timeoutsRef.current.forEach((h) => clearTimeout(h));
    timeoutsRef.current.clear();
  }, []);

  const fireExpiry = useCallback(
    (timer: ActiveTimer) => {
      if (handledRef.current.has(timer.id)) return;
      handledRef.current.add(timer.id);
      toast({
        title: t("timerAlarm.title"),
        description: t("timerAlarm.expired", { name: timer.name }),
        duration: Infinity,
      });
      playChime();
    },
    [toast, t]
  );

  const scheduleAll = useCallback(
    (timers: ActiveTimer[]) => {
      clearTimeouts();
      const nowMs = Date.now();
      for (const timer of timers) {
        if (timer.status !== "running") continue;
        if (handledRef.current.has(timer.id)) continue;
        const dueMs = new Date(timer.expires_at).getTime();
        const delay = dueMs - nowMs;
        if (delay <= 0) {
          // Already past. Alarm now if the tab is visible; otherwise leave it
          // for the visibility handler to catch up.
          if (document.visibilityState === "visible") fireExpiry(timer);
          continue;
        }
        const h = setTimeout(() => fireExpiry(timer), delay);
        timeoutsRef.current.set(timer.id, h);
      }
    },
    [clearTimeouts, fireExpiry]
  );

  const refresh = useCallback(async () => {
    if (!user) return;
    try {
      const { timers } = await getActiveTimers();
      timersRef.current = timers;
      // Drop handled ids that are no longer active (deleted / acknowledged) so
      // a re-used name can alarm again later.
      const activeIds = new Set(timers.map((x) => x.id));
      handledRef.current.forEach((id) => {
        if (!activeIds.has(id)) handledRef.current.delete(id);
      });
      scheduleAll(timers);
    } catch {
      // Network hiccup — keep the existing schedule, try again next poll.
    }
  }, [user, scheduleAll]);

  // Catch-up on returning to the foreground.
  const handleVisibility = useCallback(() => {
    if (document.visibilityState !== "visible") return;
    const nowMs = Date.now();
    for (const timer of timersRef.current) {
      if (handledRef.current.has(timer.id)) continue;
      const dueMs = new Date(timer.expires_at).getTime();
      const overdueBy = nowMs - dueMs;
      if (overdueBy <= 0) continue;
      handledRef.current.add(timer.id);
      if (overdueBy <= CATCH_UP_WINDOW_MS) {
        toast({
          title: t("timerAlarm.title"),
          description: t("timerAlarm.expiredAgo", {
            name: timer.name,
            ago: formatAgo(overdueBy, t),
          }),
          duration: Infinity,
        });
        playChime();
      }
    }
    // Re-sync with the server (authoritative).
    void refresh();
  }, [toast, t, refresh]);

  useEffect(() => {
    if (!user) return;
    void refresh();
    const poll = setInterval(refresh, POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", handleVisibility);
    const onChanged = () => void refresh();
    window.addEventListener("alice:timers-changed", onChanged);
    return () => {
      clearInterval(poll);
      clearTimeouts();
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("alice:timers-changed", onChanged);
    };
  }, [user, refresh, handleVisibility, clearTimeouts]);
}
