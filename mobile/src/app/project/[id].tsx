import { useLocalSearchParams } from "expo-router";

import { useProjects } from "@/api/hooks";
import { TaskListScreen } from "@/features/tasks/TaskListScreen";

export default function ProjectScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const projects = useProjects();
  const title =
    name ?? projects.data?.find((project) => project.id === id)?.name ?? "Project";

  return (
    <TaskListScreen
      title={title}
      projectId={id}
      mode="sub"
      emptyHeadline="No open tasks"
      emptyHint="Tasks you add here join this project."
    />
  );
}
