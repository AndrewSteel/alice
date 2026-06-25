import { useState, useEffect, useCallback } from "react";
import {
  getMailboxes,
  createMailbox,
  updateMailbox,
  deleteMailbox,
  type Mailbox,
  type CreateMailboxInput,
  type UpdateMailboxInput,
  type CreateMailboxResult,
} from "@/services/mailApi";

export function useMailboxes() {
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setIsLoading(true);
    setError(null);
    try {
      const data = await getMailboxes();
      setMailboxes(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fehler beim Laden.");
    } finally {
      if (!silent) setIsLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function addMailbox(data: CreateMailboxInput): Promise<CreateMailboxResult> {
    const result = await createMailbox(data);
    await load(true);
    return result;
  }

  async function editMailbox(data: UpdateMailboxInput): Promise<void> {
    await updateMailbox(data);
    await load(true);
  }

  async function removeMailbox(id: string): Promise<void> {
    await deleteMailbox(id);
    setMailboxes((prev) => prev.filter((m) => m.id !== id));
  }

  return { mailboxes, isLoading, error, addMailbox, editMailbox, removeMailbox, reload: load };
}
