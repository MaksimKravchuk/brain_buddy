import { TaskListScreen } from "@/features/tasks/TaskListScreen";

export default function SomedayScreen() {
  return (
    <TaskListScreen
      title="Someday / maybe"
      state="someday"
      emptyHeadline="Nothing parked"
      emptyHint="Ideas you're not committing to yet live here."
    />
  );
}
