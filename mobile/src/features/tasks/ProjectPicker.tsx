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
  buildProjectPickerView,
  initialDraft,
  reducePickerDraft,
  type AttachedEntity,
  type ListPhase,
  type PickerRow,
} from "@/features/tasks/pickerState";
import { colors, fonts, minHitTarget, radii, space, type as typeScale } from "@/theme/tokens";

export interface ProjectPickerProps {
  visible: boolean;
  /** Closes without choosing. Discards nothing. */
  onClose: () => void;
  /** The task's project. `name` is absent when the device cannot resolve it. */
  value: AttachedEntity | null;
  /** FR-001 — `null` clears the project. */
  onSelect: (projectId: string | null) => void;
  /**
   * FR-004 — creates **and** attaches in one action, resolving with the new
   * project. Rejecting must leave the task's classification untouched; this
   * screen relies on that and does nothing else on failure.
   */
  onCreate: (name: string) => Promise<NamedEntity>;
  /** The list the device can offer. `null` means it holds none — see `pickerState`. */
  projects: readonly NamedEntity[] | null;
  listPhase: ListPhase;
  online: boolean;
  onRetry: () => void;
  /** FR-012 — the correlation id of the failed list request. */
  correlationId?: string;
}

/**
 * M-02 — pick a project, clear it, or create one.
 *
 * Every state this screen can be in is decided by `buildProjectPickerView`, so
 * the rows of design.md's M-02 table are asserted in
 * `__tests__/pickerState.test.ts` rather than left to a screen no test in
 * `mobile/` can render. What is left here is rendering, and it should stay that
 * way: a decision added below is a decision that leaves the test suite.
 */
export function ProjectPicker({
  visible,
  onClose,
  value,
  onSelect,
  onCreate,
  projects,
  listPhase,
  online,
  onRetry,
  correlationId,
}: ProjectPickerProps) {
  const [draft, dispatch] = useReducer(
    reducePickerDraft<AttachedEntity | null>,
    initialDraft<AttachedEntity | null>(value),
  );
  const [elapsedMs, setElapsedMs] = useState(0);
  const opened = useRef(false);

  // Depended on as primitives, not as the object: a parent that builds `value`
  // inline hands a new identity every render, and an effect keyed on that would
  // fire between keystrokes.
  const selectedId = value?.id ?? null;
  const selectedName = value?.name;

  // Reset the grace clock when the sheet opens, during render — React's
  // documented pattern for deriving from a prop change.
  const [wasVisible, setWasVisible] = useState(visible);
  if (wasVisible !== visible) {
    setWasVisible(visible);
    setElapsedMs(0);
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
    // A change arriving *while* it is open only moves the check — see `resync`.
    const justOpened = !opened.current;
    opened.current = true;
    dispatch({
      type: justOpened ? "reset" : "resync",
      selection:
        selectedId === null
          ? null
          : { id: selectedId, ...(selectedName === undefined ? {} : { name: selectedName }) },
    });
  }, [visible, selectedId, selectedName]);

  const view = buildProjectPickerView({
    list: { phase: listPhase, entities: projects, ...(correlationId ? { correlationId } : {}) },
    online,
    query: draft.query,
    elapsedMs,
    selected: draft.selection,
  });
  const busy = draft.create.status === "creating";

  const choose = (row: PickerRow) => {
    const selection = row.id === null ? null : { id: row.id, name: row.label };
    dispatch({ type: "choose", selection });
    onSelect(row.id);
    onClose();
  };

  const chooseExisting = (entity: NamedEntity) => {
    dispatch({ type: "choose", selection: entity });
    onSelect(entity.id);
    onClose();
  };

  const create = async (name: string) => {
    dispatch({ type: "create-start", name });
    try {
      // The parent creates and attaches in one action, so there is no second
      // call here to leave half-applied when it fails.
      const created = await onCreate(name);
      dispatch({ type: "create-succeeded", selection: created });
      onClose();
    } catch (error) {
      // FR-004 / User Story 2 scenario 4: the typed name stays in the field and
      // the task's classification is untouched, so a retry costs no retyping.
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
    const entity = affordance.entity;
    createRow = (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={affordance.label}
        disabled={busy}
        onPress={() => chooseExisting(entity)}
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
          editable={!busy}
          returnKeyType="done"
        />
      ) : null}

      <ScrollView style={styles.list} keyboardShouldPersistTaps="handled">
        {view.showSkeletons ? (
          <View accessible accessibilityLabel="Loading your projects">
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
              accessibilityRole="radio"
              accessibilityLabel={row.accessibilityLabel}
              accessibilityState={{ checked: row.selected, selected: row.selected, disabled: busy }}
              disabled={busy}
              onPress={() => choose(row)}
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
      <Button variant="secondary" onPress={onClose} disabled={busy}>
        Cancel
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
