"use client";

import { useTimerAlarm } from "@/hooks/useTimerAlarm";

/**
 * Mounts the PROJ-85 WebApp timer alarm. Renders nothing — it only runs the
 * hook that watches the caller's active timers and shows a toast + chime on
 * expiry. Placed inside the authenticated shell so it has an auth context.
 */
export function TimerAlarm() {
  useTimerAlarm();
  return null;
}
