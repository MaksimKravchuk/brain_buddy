/** The word for a count: "item" for one, "items" otherwise (or the given forms). */
export function pick(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

/** "1 item", "12 items", "1 task was", "2 tasks were": the count with its noun phrase. */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${pick(count, one, many)}`;
}
