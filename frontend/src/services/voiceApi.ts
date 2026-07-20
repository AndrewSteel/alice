import { fetchWithAuth } from "./fetchWithAuth";

/**
 * Voice enrollment API (PROJ-43). Talks to the alice-speech-gateway REST
 * endpoints behind nginx at /api/speech/enroll*.
 *
 *   POST   /api/speech/enroll               — upload voice samples (self)
 *   GET    /api/speech/enroll/profiles      — list enrolled users (admin)
 *   DELETE /api/speech/enroll/{user_id}     — delete a voice profile (admin)
 *   PATCH  /api/speech/enroll/{user_id}/allow — toggle allow_voice_enrollment (admin)
 *
 * The gateway derives user_id exclusively from the JWT — never from the body.
 */

const SPEECH_BASE = "/api/speech/enroll";

// ---------- Types ----------

export interface VoiceProfile {
  user_id: string;
  username: string;
  display_name: string | null;
  role: string;
  sample_count: number;
  created_at: string | null;
}

// ---------- API Functions ----------

/**
 * Uploads recorded voice samples for the authenticated user.
 * Samples are WAV blobs (16 kHz mono). The gateway extracts an embedding
 * per file and overwrites any existing profile.
 */
export async function enrollVoice(samples: Blob[]): Promise<{ samples: number }> {
  const form = new FormData();
  samples.forEach((blob, i) => {
    form.append("files", blob, `sample-${i + 1}.wav`);
  });

  let res: Response;
  try {
    // No Content-Type header — the wrapper skips it for FormData bodies so
    // the browser sets the multipart boundary.
    res = await fetchWithAuth(SPEECH_BASE, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error("Netzwerkfehler -- Stimmproben konnten nicht hochgeladen werden.");
  }

  if (res.status === 403) {
    throw new Error("Stimmregistrierung ist fuer diesen Nutzer nicht freigegeben.");
  }
  if (res.status === 422) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Eine Aufnahme war zu leise oder zu kurz. Bitte erneut versuchen.");
  }
  if (res.status === 503) {
    throw new Error("Sprechererkennung ist derzeit nicht verfuegbar.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) bei der Stimmregistrierung.`);
  }

  return res.json();
}

/**
 * Lists all enrolled voice profiles (admin only).
 */
export async function getVoiceProfiles(): Promise<VoiceProfile[]> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${SPEECH_BASE}/profiles`, {
      method: "GET",
    });
  } catch {
    throw new Error("Netzwerkfehler -- Stimmprofile konnten nicht geladen werden.");
  }

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }
  if (res.status === 503) {
    throw new Error("Sprechererkennung ist derzeit nicht verfuegbar.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Laden der Stimmprofile.`);
  }

  return res.json();
}

/**
 * Deletes a user's voice profile (admin only).
 */
export async function deleteVoiceProfile(userId: string): Promise<void> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${SPEECH_BASE}/${userId}`, {
      method: "DELETE",
    });
  } catch {
    throw new Error("Netzwerkfehler -- Stimmprofil konnte nicht geloescht werden.");
  }

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }
  if (res.status === 404) {
    throw new Error("Stimmprofil nicht gefunden.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Loeschen des Stimmprofils.`);
  }
}

/**
 * Enables or disables a user's WebApp voice-enrollment permission (admin only).
 */
export async function setVoiceEnrollmentAllowed(
  userId: string,
  allow: boolean
): Promise<void> {
  let res: Response;
  try {
    res = await fetchWithAuth(`${SPEECH_BASE}/${userId}/allow`, {
      method: "PATCH",
      body: JSON.stringify({ allow }),
    });
  } catch {
    throw new Error("Netzwerkfehler -- Berechtigung konnte nicht geaendert werden.");
  }

  if (res.status === 403) {
    throw new Error("Zugriff verweigert -- Admin-Rechte erforderlich.");
  }
  if (res.status === 404) {
    throw new Error("Nutzer nicht gefunden.");
  }
  if (!res.ok) {
    throw new Error(`Serverfehler (${res.status}) beim Aendern der Berechtigung.`);
  }
}
