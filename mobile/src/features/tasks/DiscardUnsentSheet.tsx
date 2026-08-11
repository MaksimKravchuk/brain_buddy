import { useEffect, useRef } from "react";
import { AccessibilityInfo, StyleSheet, View, findNodeHandle } from "react-native";

import { BBText } from "@/components/BBText";
import { Button } from "@/components/Button";
import { Sheet } from "@/components/Sheet";
import type { PendingClassificationChange } from "@/features/tasks/classificationTypes";
import { buildDiscardUnsentView, type DiscardTrigger } from "@/features/tasks/sheetState";
import { colors, radii, space } from "@/theme/tokens";

export interface DiscardUnsentSheetProps {
  visible: boolean;
  /** The live queue for the active identity. The count is read from it on every
   *  render, so it decrements as the drain settles entries rather than showing
   *  the number that happened to be true when the sheet opened. */
  queue: readonly PendingClassificationChange[];
  trigger: DiscardTrigger;
  online: boolean;
  /** A drain that failed while the person was deciding (FR-012). */
  error?: { message?: string; correlationId?: string } | null;
  /** Cancels the identity transition. Also what Escape and the scrim do. */
  onStay: () => void;
  /** Proceeds with the transition, discarding whatever is still unsent. */
  onContinue: () => void;
}

/**
 * M-05 — sign-out, account change or server change would lose unsent work.
 *
 * **The count, and never a list.** That was decided at human sign-off
 * (design.md, "Decisions taken at sign-off", 2) with its cost recorded: a
 * person can be told that two changes exist and that continuing destroys them,
 * never which two. Adding a list here would quietly reverse a human decision,
 * which is why `sheetState.test.ts` asserts that no identifier from the queue
 * reaches this screen.
 *
 * Every state is decided by `buildDiscardUnsentView`; this file renders. The
 * empty queue is the exception worth reading twice: with nothing left to lose
 * the sheet does not appear at all and the action it was gating proceeds — and
 * because the count is live, a queue that drains to zero while the sheet is
 * open reaches the same state and proceeds the same way.
 */
export function DiscardUnsentSheet({
  visible,
  queue,
  trigger,
  online,
  error,
  onStay,
  onContinue,
}: DiscardUnsentSheetProps) {
  const headingRef = useRef<View>(null);
  const proceeded = useRef(false);

  const view = buildDiscardUnsentView({
    queue,
    trigger,
    online,
    ...(error === undefined ? {} : { error }),
  });
  const nothingToWarnAbout = view.kind === "no-prompt";

  useEffect(() => {
    if (!visible) {
      proceeded.current = false;
      return;
    }
    if (!nothingToWarnAbout || proceeded.current) {
      return;
    }
    // design.md M-05, "empty": the sheet never appears and the action proceeds.
    // Guarded by a ref so a re-render cannot fire the transition twice.
    proceeded.current = true;
    onContinue();
  }, [visible, nothingToWarnAbout, onContinue]);

  useEffect(() => {
    if (!visible || nothingToWarnAbout) {
      return;
    }
    // design.md: the heading, never a button — the discard here is not undoable.
    const node = headingRef.current === null ? null : findNodeHandle(headingRef.current);
    if (node !== null) {
      AccessibilityInfo.setAccessibilityFocus(node);
    }
  }, [visible, nothingToWarnAbout]);

  if (view.kind !== "prompt") {
    return null;
  }

  return (
    <Sheet visible={visible} onClose={onStay}>
      <View
        ref={headingRef}
        accessible
        accessibilityRole="header"
        accessibilityLabel={view.title}
        style={styles.heading}
      >
        <BBText variant="title">{view.title}</BBText>
      </View>

      <BBText variant="body" color={colors.fg4}>
        {view.body}
      </BBText>

      {view.error ? (
        <View accessible accessibilityRole="alert" style={styles.banner}>
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

      {/* The non-destructive choice is the upper of the two. */}
      {[view.stay, view.discard].map((button) => (
        <View key={button.action} style={styles.action}>
          <Button
            variant={button.variant}
            disabled={button.disabled}
            accessibilityLabel={button.reason === null ? button.label : `${button.label}. ${button.reason}`}
            onPress={button.action === "stay" ? onStay : onContinue}
          >
            {button.label}
          </Button>
          {button.reason ? (
            // The reason is text, always. A greyed button that does not say why
            // is state communicated by colour alone, which design.md forbids.
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
  banner: {
    backgroundColor: colors.dangerBg,
    borderWidth: 1,
    borderColor: colors.dangerBorder,
    borderRadius: radii.md,
    padding: space.s3,
    gap: space.s2,
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
