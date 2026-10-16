import type { SmartAddSuggestion } from "./smartAdd";

interface SmartAddSuggestionsProps {
  suggestions: SmartAddSuggestion[];
  activeIndex: number;
  listboxId: string;
  onSelect: (suggestion: SmartAddSuggestion) => void;
}

export function SmartAddSuggestions({
  suggestions,
  activeIndex,
  listboxId,
  onSelect
}: SmartAddSuggestionsProps): React.JSX.Element | null {
  if (!suggestions.length) {
    return null;
  }

  return (
    <div
      id={listboxId}
      role="listbox"
      aria-label="Smart Add suggestions"
      className="flex flex-wrap gap-2"
    >
      {suggestions.map((suggestion, index) => {
        const optionId = `${listboxId}-option-${index}`;
        const isActive = index === activeIndex;
        return (
          <button
            key={`${suggestion.kind}-${suggestion.label}`}
            id={optionId}
            type="button"
            role="option"
            aria-selected={isActive}
            className={`rounded-control px-2.5 py-1 text-co-meta ${
              isActive
                ? "bg-ink text-ground"
                : "bg-quiet text-ink hover:bg-quiet-pressed"
            }`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onSelect(suggestion)}
          >
            {suggestion.label}
          </button>
        );
      })}
    </div>
  );
}
