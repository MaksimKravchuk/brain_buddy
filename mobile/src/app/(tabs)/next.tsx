import { TaskListScreen } from "@/features/tasks/TaskListScreen";

export default function NextScreen() {
  return (
    <TaskListScreen
      title="Next actions"
      state="next"
      emptyHeadline="No next actions"
      emptyHint="Add a next action — or dump everything on your mind with the mic above."
    />
  );
}
