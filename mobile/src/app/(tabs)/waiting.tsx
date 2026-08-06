import { TaskListScreen } from "@/features/tasks/TaskListScreen";

export default function WaitingScreen() {
  return (
    <TaskListScreen
      title="Waiting for"
      state="waiting"
      emptyHeadline="Nothing waiting"
      emptyHint="Track what you've handed off — who and what, so nothing slips."
    />
  );
}
