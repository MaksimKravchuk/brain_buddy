import { Redirect, useLocalSearchParams } from "expo-router";

import type { OpenTaskState } from "@/api/types";
import { OPEN_TASK_STATES } from "@/api/types";
import { TaskListScreen } from "@/features/tasks/TaskListScreen";

const COPY: Record<OpenTaskState, { title: string; emptyHeadline: string; emptyHint: string }> = {
  inbox: {
    title: "Inbox",
    emptyHeadline: "Inbox zero",
    emptyHint: "Capture anything below — or dump everything on your mind with the mic.",
  },
  next: {
    title: "Next actions",
    emptyHeadline: "No next actions",
    emptyHint: "Add a next action — or dump everything on your mind with the mic above.",
  },
  waiting: {
    title: "Waiting for",
    emptyHeadline: "Nothing waiting",
    emptyHint: "Track what you've handed off — who and what, so nothing slips.",
  },
  someday: {
    title: "Someday / maybe",
    emptyHeadline: "Nothing parked",
    emptyHint: "Ideas you're not committing to yet live here.",
  },
};

export default function ListScreen() {
  const { state } = useLocalSearchParams<{ state: string }>();
  if (!(OPEN_TASK_STATES as string[]).includes(state ?? "")) {
    return <Redirect href="/list/next" />;
  }
  const openState = state as OpenTaskState;
  const copy = COPY[openState];
  return (
    <TaskListScreen
      title={copy.title}
      state={openState}
      emptyHeadline={copy.emptyHeadline}
      emptyHint={copy.emptyHint}
    />
  );
}
