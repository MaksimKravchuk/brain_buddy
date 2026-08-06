import { useCallback, useMemo } from "react";

import { useProjects, useTags } from "@/api/hooks";

/** Resolve project/tag ids to display names for task rows. */
export function useClassificationNames() {
  const projects = useProjects();
  const tags = useTags();

  const projectById = useMemo(() => {
    const map = new Map<string, string>();
    for (const project of projects.data ?? []) {
      map.set(project.id, project.name);
    }
    return map;
  }, [projects.data]);

  const tagById = useMemo(() => {
    const map = new Map<string, string>();
    for (const tag of tags.data ?? []) {
      map.set(tag.id, tag.name);
    }
    return map;
  }, [tags.data]);

  const projectName = useCallback(
    (projectId: string | null) => (projectId ? projectById.get(projectId) : undefined),
    [projectById],
  );

  const tagNames = useCallback(
    (tagIds: string[]) =>
      tagIds.map((id) => tagById.get(id)).filter((name): name is string => Boolean(name)),
    [tagById],
  );

  return { projectName, tagNames };
}
