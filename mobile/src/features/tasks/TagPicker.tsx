import { Check, Plus } from "lucide-react-native";
import { useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { Pressable, ScrollView, StyleSheet, TextInput, View } from "react-native";

import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Sheet } from "@/components/Sheet";
import type { NamedEntity } from "@/features/tasks/matchExisting";
import {
  SKELETON_DELAY_MS,
  buildTagPickerView,
  initialDraft,
  reducePickerDraft,
  toggleTag,
  type AttachedEntity,
  type ListPhase,
} from "@/features/tasks/pickerState";
import { colors, fonts, minHitTarget, radii, space, type as typeScale } from "@/theme/tokens";

export interface TagPickerProps {
  visible: boolean;
  /** Closes. Every toggle has already been applied, so nothing is discarded. */
  onClose: () => void;
  /**
   * The Tags the task carries, with names where the device knows them. These are
   * the rows in M-03's "offline, never fetched" state — sourced from the task
   * rather than the list, which is what keeps FR-002's detach reachable on a
   * first-ever visit with no connection.
   */
  attached: readonly AttachedEntity[];
  /** FR-002 — the whole intended set, sent as one set rather than per-Tag deltas. */
  onChange: (tagIds: string[]) => void;
  /**
   * FR-004 — creates **and** attaches in one action, resolving with the new Tag.
   * Rejecting must leave the task's Tags untouched; this screen relies on that
   * and does nothing else on failure.
   */
  onCreate: (name: string) => Promise<NamedEntity>;
  /** The list the device can offer. `null` means it holds none — see `pickerState`. */
  tags: readonly NamedEntity[] | null;
  listPhase: ListPhase;
  online: boolean;
  onRetry: () => void;
  /** FR-012 — the correlation id of the failed list request. */
  correlationId?: string;
}

/**
 * M-03 — attach and detach Tags, and create one when there is a connection.
 *
 * Multi-select, and every toggle applies immediately: design.md's affordance map
 * gives the toggle to the row itself, so a trailing "Cancel" that did not revert
 * would be a lie. "Done" only closes.
 *
 * Like `ProjectPicker`, every state is decided by `buildTagPickerView` and
 * asserted in `__tests__/pickerState.test.ts`; this file renders and nothing
 * more.
 */
/** The snapshot plus anything newly attached, first occurrence wins. */
function mergeRowSource(
  snapshot: readonly AttachedEntity[],
  live: readonly AttachedEntity[],
): AttachedEntity[] {
  const merged = [...snapshot];
  for (const entity of live) {
    if (!merged.some((existing) => existing.id === entity.id)) {
      merged.push(entity);
    }
  }
  return merged;
}

export function TagPicker({
  visible,
  onClose,
  attached,
  onChange,
  onCreate,
  tags,
  listPhase,
  online,
  onRetry,
  correlationId,
}: TagPickerProps) {
  const [draft, dispatch] = useReducer(
    reducePickerDraft<string[]>,
    initialDraft<string[]>(attached.map((tag) => tag.id)),
  );
  const [elapsedMs, setElapsedMs] = useState(0);
  const opened = useRef(false);

  // Depended on as one primitive, not as the array: a parent that builds
  // `attached` inline hands a new identity every render, and an effect keyed on
  // that would fire between keystrokes. NUL, because it cannot occur in an id.
  const attachedKey = attached.map((tag) => tag.id).join("\u0000");

  // Reset the grace clock when the sheet opens, during render — React's
  // documented pattern for deriving from a prop change.
  //
  // `rowSource` is snapshotted at the same moment and is what the rows are
  // built from, because `attached` is recomputed by the screen from the
  // *optimistic* value: detach the only Tag on a first-ever offline visit and
  // the live prop empties, taking the row with it and leaving nothing to tap
  // to undo. design.md's M-03 promises that detach is undoable without a
  // connection, and reading the live prop quietly broke that promise. The
  // pure-module test passed only because it holds `attached` fixed while
  // `selected` empties — a pairing the wiring never produces.
  const [wasVisible, setWasVisible] = useState(visible);
  const [rowSource, setRowSource] = useState<readonly AttachedEntity[]>(attached);
  if (wasVisible !== visible) {
    setWasVisible(visible);
    setElapsedMs(0);
    setRowSource(attached);
  }

  useEffect(() => {
    if (!visible) {
      return;
    }
    // The skeleton grace: nothing is shown for the first 300 ms, so a list that
    // arrives quickly never flashes a placeholder. The reset happens during
    // render below, not here — setting state synchronously in an effect costs
    // a cascading render, which is what `react-hooks/set-state-in-effect` is
    // for. Only the timer belongs in an effect.
    const timer = setTimeout(() => setElapsedMs(SKELETON_DELAY_MS), SKELETON_DELAY_MS);
    return () => clearTimeout(timer);
  }, [visible]);

  useEffect(() => {
    if (!visible) {
      opened.current = false;
      return;
    }
    // The sheet stays mounted while hidden, so reopening it re-reads the task.
    // A change arriving *while* it is open — the person's own toggle coming back
    // through the props, or a queue drain — only moves the checks, so a
    // half-typed name survives it.
    const justOpened = !opened.current;
    opened.current = true;
    dispatch({
      type: justOpened ? "reset" : "resync",
      selection: attachedKey === "" ? [] : attachedKey.split("\u0000"),
    });
  }, [visible, attachedKey]);

  const view = buildTagPickerView({
    list: { phase: listPhase, entities: tags, ...(correlationId ? { correlationId } : {}) },
    online,
    query: draft.query,
    elapsedMs,
    // Union so a Tag attached while the sheet is open still gets a row.
    attached: mergeRowSource(rowSource, attached),
    selected: draft.selection,
  });
  const busy = draft.create.status === "creating";

  const toggle = (tagId: string) => {
    const next = toggleTag(draft.selection, tagId);
    dispatch({ type: "choose", selection: next });
    onChange(next);
  };

  const create = async (name: string) => {
    dispatch({ type: "create-start", name });
    try {
      // The parent creates and attaches in one action, so there is no second
      // call here to leave half-applied when it fails.
      const created = await onCreate(name);
      dispatch({ type: "create-succeeded", selection: [...draft.selection, created.id] });
    } catch (error) {
      // FR-004 / User Story 2 scenario 4: the typed name stays in the field and
      // the task's Tags are untouched, so a retry costs no retyping.
      dispatch({ type: "create-failed", error });
    }
  };

  const affordance = view.create;
  let createRow: ReactNode = null;
  if (affordance.kind === "create") {
    const name = affordance.name;
    createRow = (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={affordance.label}
        accessibilityState={{ disabled: busy }}
        disabled={busy}
        onPress={() => void create(name)}
        style={styles.createRow}
      >
        <Plus size={16} color={colors.brandPrimary} strokeWidth={2} />
        <BBText variant="subtitle" weight="semibold" color={colors.brandPrimary}>
          {affordance.label}
        </BBText>
      </Pressable>
    );
  } else if (affordance.kind === "use-existing") {
    const entityId = affordance.entity.id;
    createRow = (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={affordance.label}
        disabled={busy}
        onPress={() => toggle(entityId)}
        style={styles.row}
      >
        <BBText variant="subtitle" weight="regular" style={styles.rowLabel}>
          {affordance.label}
        </BBText>
      </Pressable>
    );
  } else if (affordance.kind === "already-chosen") {
    createRow = (
      <View accessible accessibilityRole="text" style={styles.staticRow}>
        <BBText variant="subtitle" weight="regular" color={colors.fg5}>
          {affordance.label}
        </BBText>
      </View>
    );
  } else if (affordance.kind === "blocked") {
    createRow = (
      <Pressable
        accessibilityRole="button"
        // FR-016: the reason is part of the accessible name, so it is heard
        // before the row is tapped rather than after the create fails.
        accessibilityLabel={`${affordance.label}. ${affordance.reason}`}
        accessibilityState={{ disabled: true }}
        disabled
        style={[styles.createRow, styles.createRowBlocked]}
      >
        <Plus size={16} color={colors.fg6} strokeWidth={2} />
        <View style={styles.blockedText}>
          <BBText variant="subtitle" weight="semibold" color={colors.fg5}>
            {affordance.label}
          </BBText>
          <BBText variant="micro" color={colors.fg5}>
            {affordance.reason}
          </BBText>
        </View>
      </Pressable>
    );
  }

  return (
    <Sheet visible={visible} onClose={onClose} title={view.title}>
      {view.message ? (
        <View
          accessible
          accessibilityRole={view.initialFocus === "message" ? "alert" : "text"}
          style={[
            styles.banner,
            view.message.tone === "error" ? styles.bannerError : styles.bannerInfo,
          ]}
        >
          <BBText
            variant="body"
            color={view.message.tone === "error" ? colors.dangerFg : colors.fg4}
          >
            {view.message.text}
          </BBText>
          {view.message.correlationId ? (
            <BBText variant="micro" color={colors.fg5} style={styles.correlation}>
              {`ref: ${view.message.correlationId}`}
            </BBText>
          ) : null}
          {view.message.retry ? (
            <Button variant="secondary" onPress={onRetry} style={styles.retry}>
              Retry
            </Button>
          ) : null}
        </View>
      ) : null}

      {view.offlineBanner ? (
        <View style={[styles.banner, styles.bannerWarning]}>
          <BBText variant="body" color={colors.warningFg}>
            {view.offlineBanner}
          </BBText>
        </View>
      ) : null}

      {view.search.shown ? (
        <TextInput
          style={styles.input}
          value={draft.query}
          onChangeText={(next) => dispatch({ type: "query", value: next })}
          placeholder={view.search.placeholder}
          placeholderTextColor={colors.fg6}
          accessibilityLabel={view.search.placeholder}
          autoFocus={view.initialFocus === "search"}
          autoCorrect={false}
          autoCapitalize="none"
          editable={!busy}
          returnKeyType="done"
        />
      ) : null}

      <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
        {view.showSkeletons ? (
          <View accessible accessibilityLabel="Loading your Tags">
            {Array.from({ length: view.skeletonRows }, (_unused, index) => (
              <View
                key={index}
                accessibilityElementsHidden
                importantForAccessibility="no-hide-descendants"
                style={styles.skeleton}
              />
            ))}
          </View>
        ) : (
          view.rows.map((row) => (
            <Pressable
              key={row.key}
              accessibilityRole="checkbox"
              accessibilityLabel={row.accessibilityLabel}
              accessibilityState={{ checked: row.selected, disabled: busy }}
              disabled={busy}
              onPress={() => {
                // The Tag picker never builds a "None" row — a Tag is cleared by
                // detaching it — but `PickerRow` is shared with M-02, which does.
                if (row.id !== null) {
                  toggle(row.id);
                }
              }}
              style={[styles.row, row.selected ? styles.rowSelected : null]}
            >
              <BBText variant="subtitle" weight="regular" numberOfLines={1} style={styles.rowLabel}>
                {row.label}
              </BBText>
              {row.selected ? (
                <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
                  <Check size={18} color={colors.brandPrimary} strokeWidth={2.5} />
                </View>
              ) : null}
            </Pressable>
          ))
        )}
        {createRow}
      </ScrollView>

      {draft.create.status === "failed" ? <ErrorBanner error={draft.create.error} /> : null}

      <BBText variant="caption" color={colors.fg5} style={styles.footer}>
        {view.footer}
      </BBText>
      <Button onPress={onClose} disabled={busy}>
        Done
      </Button>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  banner: {
    borderRadius: radii.md,
    borderWidth: 1,
    padding: space.s3,
    gap: space.s2,
  },
  bannerInfo: {
    backgroundColor: colors.surfaceSunken,
    borderColor: colors.border,
  },
  bannerWarning: {
    backgroundColor: colors.warningBg,
    borderColor: colors.warningBorder,
  },
  bannerError: {
    backgroundColor: colors.dangerBg,
    borderColor: colors.dangerBorder,
  },
  correlation: {
    fontFamily: "Menlo",
  },
  retry: {
    alignSelf: "flex-start",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.sm,
    paddingHorizontal: space.s3,
    paddingVertical: space.s3,
    fontSize: typeScale.body,
    fontFamily: fonts.regular,
    color: colors.fg1,
    backgroundColor: colors.surfaceRaised,
    minHeight: minHitTarget,
  },
  list: {
    maxHeight: 320,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.s2,
    minHeight: 48,
    paddingHorizontal: 14,
    paddingVertical: space.s2,
    marginBottom: space.s2,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radii.md,
    backgroundColor: colors.surfaceRaised,
  },
  rowSelected: {
    borderColor: colors.brandPrimary,
  },
  rowLabel: {
    flex: 1,
  },
  staticRow: {
    minHeight: 48,
    justifyContent: "center",
    paddingHorizontal: 14,
    marginBottom: space.s2,
  },
  // No pulse: ambient animation belongs to the brain dump alone.
  skeleton: {
    height: 14,
    borderRadius: radii.sm,
    marginBottom: space.s3,
    backgroundColor: colors.surfaceSunken,
  },
  createRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    minHeight: 48,
    paddingHorizontal: 14,
    paddingVertical: space.s2,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.fg7,
    borderRadius: radii.md,
  },
  createRowBlocked: {
    backgroundColor: colors.surfaceSunken,
  },
  blockedText: {
    flex: 1,
    gap: 2,
  },
  footer: {
    textAlign: "center",
  },
});
