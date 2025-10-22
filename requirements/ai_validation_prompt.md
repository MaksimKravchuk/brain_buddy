# AI Validation Prompt Draft

## Objective
- Evaluate the logical consistency of a reasoning chain leading from the highest node to the selected node in a Current Reality Tree.
- Provide a confidence percentage (0–100) representing how well each causal transition is justified.
- Surface succinct feedback highlighting strong/weak links and suggested questions for the user.

## Prompt Template (OpenAI style)
```
System:
You are an expert in the Theory of Constraints and causal analysis. 
Judge whether each causal link in a Current Reality Tree is well supported.
Output JSON only, matching the schema provided.

User:
Context:
- Tree title: {{tree_title}}
- Selected node: "{{selected_node.label}}"
- Chain length: {{chain_length}} links

Causal Chain (top -> bottom):
{% for step in chain %}
Step {{loop.index}}:
- Effect node: "{{step.effect.label}}"
- Relation question: "{{step.relation.question_label}}"
- Cause node: "{{step.cause.label}}"
- Relation notes: "{{step.relation.notes | default('None')}}"
- Existing validation: {{step.effect.validation_summary | default('None')}}
{% endfor %}

Task:
1. Assess each link for logical plausibility and sufficiency given the information.
2. Identify any assumptions, contradictions, or missing evidence.
3. Provide an overall confidence score (0–100).
4. Suggest up to 3 actionable questions or checks the user should consider.

Output JSON schema:
{
  "confidence": number,                // 0-100
  "verdict": "strong" | "uncertain" | "weak",
  "observations": [
    {
      "link_index": number,            // 1-based position in chain
      "assessment": string,            // concise judgment of that link
      "severity": "info" | "warning" | "error"
    }
  ],
  "suggested_questions": [string]       // up to 3
}
```

## Response Parsing
- Backend validates JSON against schema; reject responses that include extra text.
- `confidence` mapped to UI highlight colors.  
  - 85–100 → strong (green)  
  - 60–84 → uncertain (amber)  
  - 0–59 → weak (red)
- `observations` inform tooltip content per relation; `severity` dictates icon.

## Evaluation Rubric
- **Logical Sufficiency**: Does the cause adequately explain the effect?  
  - Strong: clear, evidence-based relationship.  
  - Warning: plausible but missing supporting detail.  
  - Error: contradictory or unrelated cause.
- **Completeness**: Are key contributing factors missing?  
  - Consider whether multiple causes are required.  
  - Flag gaps when a single cause seems insufficient.
- **Consistency**: Are there conflicting statements within the chain?  
  - Highlight circular reasoning or mutually exclusive causes.
- **Clarity**: Are relation labels/questions specific enough?  
  - Encourage refining vague labels (e.g., “WHY?” → “WHY does X happen?”).
- **Actionability**: Provide questions that help the user gather evidence or clarify assumptions.

## Provider Variations
- For Anthropic or others, adapt prompt syntax but keep schema and instructions.
- Maintain versioned prompt templates (e.g., `validation_v1`). Track in provider config and include `prompt_version` in stored validation results.

## Safety & Cost Notes
- Enforce max chain length per call (e.g., 20 steps) to control token usage; split chains if longer.
- Truncate node labels/notes beyond 512 characters with ellipsis, retaining raw data client-side.
- Rate-limit validation requests per tree/user to avoid accidental spamming.
