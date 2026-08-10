import { useState } from "react";

/**
 * An editable draft of a server-owned string.
 *
 * The draft follows the server copy until the user types, and follows it again
 * as soon as a new `key` arrives — a new revision, a reconciled proposal, a
 * refetch after a 409. Edits in progress are the user's to redo deliberately;
 * the server copy is never silently overwritten.
 *
 * The obvious implementation of that rule is an effect that calls `setState`
 * when the key changes, which cascades an extra render and trips
 * `react-hooks/set-state-in-effect`. Storing the key *with* the draft removes
 * the need to synchronise anything: a draft that does not belong to the
 * current key simply is not shown.
 *
 * A draft therefore belongs to the key it was typed under. If that same key
 * comes back — a proposal title reconciled away and then back again — so does
 * the draft, which is the useful reading: the edit was made against exactly
 * the value on screen now. Keys that only move forward (a task revision)
 * never exercise that.
 *
 * @param serverValue the value the server currently holds
 * @param key changes exactly when the draft should be abandoned; defaults to
 *   the server value itself, which is the right key whenever any server-side
 *   change should win
 */
export function useServerDraft(
  serverValue: string,
  key: string = serverValue,
): [string, (next: string) => void] {
  const [draft, setDraft] = useState<{ key: string; value: string } | null>(null);
  const value = draft !== null && draft.key === key ? draft.value : serverValue;
  return [value, (next: string) => setDraft({ key, value: next })];
}
