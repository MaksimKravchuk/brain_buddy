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
            className={`rounded-full border px-2.5 py-1 text-xs shadow-soft ${
              isActive
                ? "border-sky-300 bg-sky-50 text-sky-800"
                : "border-sky-100 bg-white text-sky-700 hover:border-sky-200 hover:bg-sky-50"
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
