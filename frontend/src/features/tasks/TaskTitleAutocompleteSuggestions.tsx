interface Props {
  candidates: string[];
  activeIndex: number;
  listboxId: string;
  onSelect: (candidate: string, rank: number) => void;
}

export function TaskTitleAutocompleteSuggestions({
  candidates,
  activeIndex,
  listboxId,
  onSelect
}: Props): React.JSX.Element | null {
  if (candidates.length !== 3) return null;

  return (
    <div
      id={listboxId}
      role="listbox"
      aria-label="Task title suggestions"
      className="grid gap-1 rounded-card bg-card p-2"
    >
      {candidates.map((candidate, index) => (
        <button
          key={candidate}
          id={`${listboxId}-option-${index}`}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          className={`rounded-lg px-3 py-2 text-left text-co-meta ${
            index === activeIndex ? "bg-quiet text-ink" : "text-ink hover:bg-sunken"
          }`}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onSelect(candidate, index + 1)}
        >
          {candidate}
        </button>
      ))}
    </div>
  );
}
