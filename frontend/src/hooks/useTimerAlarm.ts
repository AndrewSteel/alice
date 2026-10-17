"use client";

/**
 * useTimerAlarm — PROJ-85 WebApp timer alarm.
 *
 * Timers are created / changed / deleted through the chat; this hook only
 * shows the alarm. It:
 *   - loads the caller's role-scoped timers from the server (authoritative
 *     source) on mount, on an interval, on tab focus and when the chat
 *     signals a timer change ("alice:timers-changed") — the active ones plus
 *     those that expired recently and nobody actively acknowledged
 *   - counts down locally to each running timer's absolute `expires_at`
 *   - when a countdown reaches zero while the tab is visible: a toast (stays
 *     until dismissed) + a short chime
 *   - when the tab is visible after an expiry it did not alarm live: a
 *     catch-up toast ("… ist vor X abgelaufen") for every timer the server
 *     still reports as expired — a timer acknowledged meanwhile by voice or
 *     another tab is no longer reported, so there is no stale catch-up
 *   - closing a toast acknowledges the alarm server-side, which also stops
 *     the melody on all Voice PE (Refinement 2026-10-15); a toast whose timer
 *     the server no longer reports (acknowledged elsewhere, deleted) closes
 *     itself on the next sync
 *
 * Reliable background notification (locked screen / closed tab) is out of
 * scope — that is PROJ-104 (Web Push).
 */

import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";

import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/useAuth";
import {
  acknowledgeTimers,
  getActiveTimers,
  type ActiveTimer,
} from "@/services/timers";

// The chat fires `alice:timers-changed` on every timer create, so the poll is
// only a safety net for changes made from another device / voice. 2 min keeps
// it light on the (separate) timer rate-limit budget. The catch-up window
// (spec "Nachhol-Fenster", 15 min) is applied server-side.
const POLL_INTERVAL_MS = 120_000;

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
  // Open alarm toasts, by timer id. An entry is removed before a programmatic
  // dismiss, so a close with the entry still present was the user's.
  const toastsRef = useRef<Map<string, () => void>>(new Map());
  // Per-timer countdown timeout handles.
  const timeoutsRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const clearTimeouts = useCallback(() => {
    timeoutsRef.current.forEach((h) => clearTimeout(h));
    timeoutsRef.current.clear();
  }, []);

  const showAlarm = useCallback(
    (timer: ActiveTimer, description: string) => {
      if (handledRef.current.has(timer.id)) return;
      handledRef.current.add(timer.id);
      const { dismiss } = toast({
        title: t("timerAlarm.title"),
        description,
        duration: Infinity,
        onOpenChange: (open) => {
          if (open || !toastsRef.current.has(timer.id)) return;
          toastsRef.current.delete(timer.id);
          // Best effort — on failure the alarm still ends by voice / timeout.
          acknowledgeTimers([timer.id]).catch(() => {});
        },
      });
      toastsRef.current.set(timer.id, dismiss);
      playChime();
    },
    [toast, t]
  );

  const fireExpiry = useCallback(
    (timer: ActiveTimer) => {
      // Hidden tab: no toast now; the next sync on return reports it if
      // nobody acknowledged it meanwhile.
      if (document.visibilityState !== "visible") return;
      showAlarm(timer, t("timerAlarm.expired", { name: timer.name }));
    },
    [showAlarm, t]
  );

  const catchUp = useCallback(
    (timers: ActiveTimer[]) => {
      if (document.visibilityState !== "visible") return;
      const nowMs = Date.now();
      for (const timer of timers) {
        if (timer.status !== "expired") continue;
        const overdueBy = Math.max(0, nowMs - new Date(timer.expires_at).getTime());
        showAlarm(
          timer,
          t("timerAlarm.expiredAgo", { name: timer.name, ago: formatAgo(overdueBy, t) })
        );
      }
    },
    [showAlarm, t]
  );

  const scheduleAll = useCallback(
    (timers: ActiveTimer[]) => {
      clearTimeouts();
      const nowMs = Date.now();
      for (const timer of timers) {
        if (timer.status !== "running") continue;
        if (handledRef.current.has(timer.id)) continue;
        const delay = new Date(timer.expires_at).getTime() - nowMs;
        if (delay <= 0) {
          // Already past but not yet fired server-side.
          fireExpiry(timer);
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
      const listedIds = new Set(timers.map((x) => x.id));
      // Acknowledged elsewhere (voice, another tab) or deleted: close the
      // toast here too, and forget the id so a re-used name can alarm again.
      toastsRef.current.forEach((dismiss, id) => {
        if (listedIds.has(id)) return;
        toastsRef.current.delete(id);
        dismiss();
      });
      handledRef.current.forEach((id) => {
        if (!listedIds.has(id)) handledRef.current.delete(id);
      });
      scheduleAll(timers);
      catchUp(timers);
    } catch {
      // Network hiccup — keep the existing schedule, try again next poll.
    }
  }, [user, scheduleAll, catchUp]);

  useEffect(() => {
    if (!user) return;
    void refresh();
    const poll = setInterval(refresh, POLL_INTERVAL_MS);
    // Back in the foreground: sync first, then catch up from server state.
    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    const onChanged = () => void refresh();
    window.addEventListener("alice:timers-changed", onChanged);
    return () => {
      clearInterval(poll);
      clearTimeouts();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("alice:timers-changed", onChanged);
    };
  }, [user, refresh, clearTimeouts]);
}
