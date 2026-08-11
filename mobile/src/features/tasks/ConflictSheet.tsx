import { useEffect, useRef, useState } from "react";
import { AccessibilityInfo, ScrollView, StyleSheet, View, findNodeHandle } from "react-native";

import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { Sheet } from "@/components/Sheet";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { rejectionFromError, type DecisionReason } from "@/features/tasks/conflictDecision";
import {
  buildConflictView,
  type ConflictChoice,
  type ConflictNames,
  type ConflictResolutionState,
  type ConflictServerState,
} from "@/features/tasks/sheetState";
import type { Instant } from "@/features/tasks/syncStatus";
import { colors, radii, space } from "@/theme/tokens";

export interface ConflictSheetProps {
  visible: boolean;
  /** From `selectPendingConflict` — one sheet per task, oldest first. */
  conflict: { entry: PendingClassificationChange; index: number; total: number } | undefined;
  /** The task as the drain's re-read found it. `null` when it could not. */
  server: ConflictServerState | null;
  /**
   * From `decideOnRejection`. `conflicted` alone does **not** mean a revision
   * conflict — a 404 on a deleted target parks an entry the same way, and that
   * case has only one honest choice.
   */
  reason: DecisionReason;
  names: ConflictNames;
  /** When the device last read this task from the server, if anything knows. */
  deviceObservedAt?: Instant | null;
  /** FR-012 — the correlation id of the rejection that opened this sheet. */
  correlationId?: string;
  /** Which target a 404 named, when the client knows. */
  missingTarget?: "task" | "project" | "tag";
  /** Re-sends against the current revision. Rejecting leaves the entry alone. */
  onKeepMine: () => Promise<void>;
  /** Drops the queued entry. Rejecting leaves the entry alone. */
  onDiscardMine: () => Promise<void>;
  /** Escape, the scrim, or backgrounding: "not yet answered". Resolves nothing,
   *  discards nothing, and the sheet returns. */
  onDismiss: () => void;
  /** Overrides the clock this sheet reads on open. Injectable for the same
   *  reason `formatAge` takes it as an argument. */
  now?: Instant;
}

/**
 * M-04 — the server rejected a queued change and the person chooses.
 *
 * Every state this sheet can be in is decided by `buildConflictView`, so the
 * rows of design.md's M-04 table are asserted in `__tests__/sheetState.test.ts`
 * rather than left to a screen is now covered by render tests (main added a fake-backend harness after this was written). What is left
 * here is rendering, and it should stay that way: a decision added below is a
 * decision that leaves the test suite.
 *
 * The one thing this file owns is the in-flight state, because it is the only
 * thing that knows when the parent's promise settles.
 */
export function ConflictSheet({
  visible,
  conflict,
  server,
  reason,
  names,
  deviceObservedAt,
  correlationId,
  missingTarget,
  onKeepMine,
  onDiscardMine,
  onDismiss,
  now,
}: ConflictSheetProps) {
  const [resolution, setResolution] = useState<ConflictResolutionState>({ status: "idle" });
  const [clock, setClock] = useState<number | null>(null);
  const headingRef = useRef<View>(null);
  const entryKey = conflict?.entry.idempotencyKey;

  // Clearing the clock when the sheet closes is a prop-change derivation, so
  // it happens during render alongside the resolution reset below.
  const [clockFor, setClockFor] = useState(`${entryKey}:${visible}`);
  if (clockFor !== `${entryKey}:${visible}`) {
    setClockFor(`${entryKey}:${visible}`);
    setClock(null);
  }

  useEffect(() => {
    if (!visible) {
      return;
    }
    // The clock cannot be read during render — React's purity rule — and
    // cannot be set synchronously here either, because that cascades a render
    // (`react-hooks/set-state-in-effect`). Reading it from a scheduled task
    // satisfies both, and costs nothing the design did not already accept:
    // `buildConflictView` takes `now` as an argument precisely so the age is
    // omitted until a real instant exists, which is the honest thing to show
    // rather than dating a three-week-old change as "just now".
    const scheduled = setTimeout(() => setClock(Date.now()), 0);
    return () => clearTimeout(scheduled);
  }, [visible, entryKey]);

  // A different conflict, or a reopen, is a fresh question: a failure carried
  // over from the previous one would show its correlation id against a task it
  // has nothing to do with. Reset during render rather than in an effect —
  // setting state synchronously in an effect cascades a render.
  const [lastQuestion, setLastQuestion] = useState(`${entryKey}:${visible}`);
  if (lastQuestion !== `${entryKey}:${visible}`) {
    setLastQuestion(`${entryKey}:${visible}`);
    setResolution({ status: "idle" });
  }

  useEffect(() => {
    if (!visible) {
      return;
    }
    // design.md: focus the heading, never a button, so no destructive action is
    // one keypress from an accidental confirm.
    const node = headingRef.current === null ? null : findNodeHandle(headingRef.current);
    if (node !== null) {
      AccessibilityInfo.setAccessibilityFocus(node);
    }
  }, [visible, entryKey]);

  if (!conflict) {
    return null;
  }

  const view = buildConflictView({
    entry: conflict.entry,
    server,
    reason,
    names,
    deviceObservedAt: deviceObservedAt ?? null,
    now: now ?? clock,
    index: conflict.index,
    total: conflict.total,
    resolution,
    ...(correlationId === undefined ? {} : { correlationId }),
    ...(missingTarget === undefined ? {} : { missingTarget }),
  });

  if (view.kind !== "prompt") {
    // "Already applied": the server holds exactly what the entry intended, so
    // there is no disagreement to put to anyone. Prompting here would invent a
    // decision — design.md's one explicit exception to SC-005.
    return null;
  }

  const choose = async (choice: ConflictChoice) => {
    setResolution({ status: "sending", choice });
    try {
      await (choice === "keep-mine" ? onKeepMine() : onDiscardMine());
      setResolution({ status: "idle" });
    } catch (error) {
      // FR-012: the correlation id travels with the failure. `rejectionFromError`
      // already knows how to dig it out of whatever the client threw.
      const rejection = rejectionFromError(error);
      setResolution({
        status: "failed",
        choice,
        ...(rejection.serverMessage === undefined ? {} : { message: rejection.serverMessage }),
        ...(rejection.correlationId === undefined ? {} : { correlationId: rejection.correlationId }),
      });
    }
  };

  return (
    <Sheet visible={visible} onClose={onDismiss}>
      <View
        ref={headingRef}
        accessible
        accessibilityRole="header"
        accessibilityLabel={[view.progressLabel, view.title].filter(Boolean).join(". ")}
        style={styles.heading}
      >
        {view.progressLabel ? <BBText variant="label">{view.progressLabel}</BBText> : null}
        <BBText variant="title">{view.title}</BBText>
      </View>

      <BBText variant="body" color={colors.fg4}>
        {view.body}
      </BBText>

      <ScrollView style={styles.sections} contentContainerStyle={styles.sectionsContent}>
        {view.sections.map((section) => (
          <View key={section.field} style={styles.section}>
            {section.heading ? (
              <BBText variant="caption" weight="semibold" color={colors.fg4}>
                {section.heading}
              </BBText>
            ) : null}
            {section.rows.map((row) => (
              <View key={row.key} accessible accessibilityLabel={row.accessibilityLabel} style={styles.row}>
                <BBText variant="micro" color={colors.fg5} style={styles.rowLabel}>
                  {row.label}
                </BBText>
                <View style={styles.rowValue}>
                  <BBText variant="body" color={colors.fg1}>
                    {row.value}
                  </BBText>
                  {row.note ? (
                    <BBText variant="micro" color={colors.fg5}>
                      {row.note}
                    </BBText>
                  ) : null}
                </View>
              </View>
            ))}
          </View>
        ))}
      </ScrollView>

      {view.multiChangeNotice ? (
        <View style={[styles.banner, styles.bannerInfo]}>
          <BBText variant="caption" color={colors.fg4}>
            {view.multiChangeNotice}
          </BBText>
        </View>
      ) : null}

      {view.error ? (
        <View accessible accessibilityRole="alert" style={[styles.banner, styles.bannerError]}>
          <BBText variant="body" color={colors.dangerFg}>
            {view.error.text}
          </BBText>
          {view.error.detail ? (
            <BBText variant="micro" color={colors.fg5}>
              {view.error.detail}
            </BBText>
          ) : null}
        </View>
      ) : null}

      {view.buttons.map((button) => (
        <View key={button.choice} style={styles.action}>
          <Button
            variant={button.variant}
            disabled={button.disabled}
            loading={button.busy}
            // The reason is part of the accessible name, so it is heard rather
            // than inferred from the button looking greyed.
            accessibilityLabel={button.reason === null ? button.label : `${button.label}. ${button.reason}`}
            onPress={() => void choose(button.choice)}
          >
            {button.label}
          </Button>
          {button.reason ? (
            <BBText variant="micro" color={colors.fg5} style={styles.reason}>
              {button.reason}
            </BBText>
          ) : null}
        </View>
      ))}

      {view.correlationLine ? (
        <BBText variant="micro" color={colors.fg5} style={styles.correlation}>
          {view.correlationLine}
        </BBText>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  heading: {
    gap: space.s1,
  },
  sections: {
    maxHeight: 320,
  },
  sectionsContent: {
    gap: space.s3,
  },
  section: {
    backgroundColor: colors.surfaceSunken,
    borderRadius: radii.md,
    padding: space.s3,
    gap: space.s2,
  },
  // Vertical rows, one value per line. Three Tag sets side by side do not fit
  // 390 px, so they are never laid out that way.
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: space.s2,
  },
  rowLabel: {
    width: 118,
    flexShrink: 0,
  },
  rowValue: {
    flex: 1,
    gap: 2,
  },
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
  bannerError: {
    backgroundColor: colors.dangerBg,
    borderColor: colors.dangerBorder,
  },
  action: {
    gap: space.s1,
  },
  reason: {
    textAlign: "center",
  },
  correlation: {
    fontFamily: "Menlo",
    textAlign: "center",
  },
});
