import { TaskListScreen } from "@/features/tasks/TaskListScreen";

export default function InboxScreen() {
  return (
    <TaskListScreen
      title="Inbox"
      state="inbox"
      emptyHeadline="Inbox zero"
      emptyHint="Capture anything with a quick add — or dump everything on your mind with the mic."
    />
  );
}
