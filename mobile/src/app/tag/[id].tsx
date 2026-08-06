import { useLocalSearchParams } from "expo-router";

import { useTags } from "@/api/hooks";
import { TaskListScreen } from "@/features/tasks/TaskListScreen";

export default function TagScreen() {
  const { id, name } = useLocalSearchParams<{ id: string; name?: string }>();
  const tags = useTags();
  const title = name ?? tags.data?.find((tag) => tag.id === id)?.name ?? "Tag";

  return (
    <TaskListScreen
      title={title}
      tagId={id}
      showBack
      emptyHeadline="No open tasks"
      emptyHint="Tasks you add here keep this tag."
    />
  );
}
