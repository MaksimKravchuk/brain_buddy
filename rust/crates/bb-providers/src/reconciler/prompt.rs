//! System prompt (template `brain-dump-reconciler-v3`) and the strict response schema.

use serde_json::{Value, json};

pub const OPERATIONS: [&str; 6] = ["add", "update", "split", "merge", "remove", "supersede"];

/// An OpenAI-strict schema with every property explicitly required.
pub fn response_schema(add_only: bool) -> Value {
    let ns = json!({"anyOf": [{"type": "string"}, {"type": "null"}]});
    let ids = json!({"type": "array", "maxItems": 100, "items": {"type": "string"}});
    let ops: &[&str] = if add_only { &["add"] } else { &OPERATIONS };
    json!({"type": "object", "additionalProperties": false, "required": ["operations"],
    "properties": {"operations": {"type": "array", "maxItems": 100, "items": {
      "type": "object", "additionalProperties": false,
      "required": ["operation", "proposal_id", "title", "source_segment_ids",
                   "predecessor_ids", "base_revision", "confidence"],
      "properties": {
        "operation": {"type": "string", "enum": ops},
        "proposal_id": ns, "title": ns,
        "source_segment_ids": ids, "predecessor_ids": ids,
        "base_revision": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}]},
        "confidence": {"anyOf": [{"type": "number", "minimum": 0, "maximum": 1}, {"type": "null"}]}
      }}}}})
}

const SYSTEM: &str = concat!(
    "Convert the accurate transcript into reviewable task proposal ",
    "operations. Preserve intent, language, proper nouns, source segment ",
    "IDs, existing proposal identity, user locks, and deletions. Use only ",
    "add, update, split, merge, remove, or supersede. Never infer details, ",
    "tags, projects, priority, due dates, routes, or destructive actions. ",
    "Never invent, fabricate, or hallucinate a task whose meaning is not ",
    "actually present in the supplied transcript segments; every operation ",
    "must be grounded in and traceable to its cited source_segment_ids, and ",
    "an ambiguous or empty transcript span must not be turned into a task. ",
    "This applies to every operation shape, including update/split/merge/",
    "supersede renames. A remove must also cite the source_segment_ids that ",
    "justify deleting the proposal; never remove an existing proposal without ",
    "transcript evidence for that removal. Do not split a single shopping ",
    "intent solely on a conjunction. Write every task title in the same ",
    "language as the transcript segment(s) it cites; never translate a title ",
    "into another language. Each transcript segment is one separately spoken ",
    "utterance: do not merge content from different segments into a single ",
    "proposal unless they explicitly describe the same single action, and do ",
    "not split one segment into multiple proposals unless it clearly ",
    "enumerates independent commands. Emit one proposal for every actionable ",
    "segment; a segment may be skipped only if it is a query/display request, ",
    "a filler or self-correction, or modifies an existing proposal. ",
    "Reminder and note phrasings (for example «напомни…», ",
    "\"remind me…\", «запиши…») are actionable task ",
    "creates. Phrase every title as a GTD next action: it starts with the ",
    "concrete action verb (Russian infinitive, English base form) followed ",
    "by its object, for example «Купить молоко», «Сходить в магазин», ",
    "\"Call the dentist\". Drop discourse fillers, hesitations and modal ",
    "scaffolding that carry no action («так», «ну», «значит», «надо», ",
    "«нужно», \"so\", \"um\", \"I need to\"); a fragment with no action, such as ",
    "«Так» or «Надо», is never a task. Emit each distinct action once: when ",
    "the transcript repeats or rephrases the same action and object, produce ",
    "one proposal citing every segment that states it, never a duplicate. ",
    "Keep each title concise: the core action and its ",
    "object, using the words spoken in the source. Do not append deadlines, ",
    "dates, times, contexts, tags, labels, project names, or note ",
    "text to the title unless the title would be meaningless ",
    "without them. New ",
    "proposal IDs are server-owned: set proposal_id to null for add/split/",
    "merge/supersede. Existing update/remove targets must use an exact ",
    "supplied ID. Return every schema field; use null or [] when a field ",
    "does not apply.",
);
const ADD_ONLY: &str = " No active proposals were supplied, so only add operations are valid.";
const CONFIDENCE: &str = " Report confidence from 0 to 1 for each proposed task operation.";

pub fn system_prompt(add_only: bool) -> String {
    format!(
        "{SYSTEM}{}{CONFIDENCE}",
        if add_only { ADD_ONLY } else { "" }
    )
}
