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
      className="grid gap-1 rounded-xl border border-sky-100 bg-white p-2 shadow-soft"
    >
      {candidates.map((candidate, index) => (
        <button
          key={candidate}
          id={`${listboxId}-option-${index}`}
          type="button"
          role="option"
          aria-selected={index === activeIndex}
          className={`rounded-lg px-3 py-2 text-left text-sm ${
            index === activeIndex ? "bg-sky-50 text-sky-900" : "text-slate-700 hover:bg-slate-50"
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
