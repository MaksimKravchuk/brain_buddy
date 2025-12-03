"""Prompt builder for validation workflow."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.schemas.common import ValidationState
from app.schemas.domain import NodeDocument, RelationDocument, TreeDocument

PROMPT_VERSION = "validation_v1"
MAX_CHAIN_LENGTH = 20
TRUNCATE_LIMIT = 512


@dataclass(slots=True)
class ChainStep:
    """Represents a single effect -> cause relationship in the prompt."""

    effect: NodeDocument
    relation: RelationDocument
    cause: NodeDocument
    effect_validation_summary: str


@dataclass(slots=True)
class ValidationPrompt:
    """Rendered prompt with supporting metadata."""

    prompt: str
    steps: list[ChainStep]
    prompt_version: str = PROMPT_VERSION


def summarize_validation_state(state: ValidationState | None) -> str:
    """Render a brief human-readable summary for existing validation metadata."""

    if not state:
        return "None"
    return (
        f"{state.confidence}% via {state.provider} on {state.last_checked.isoformat()}"
    )


def truncate(value: str | None, limit: int = TRUNCATE_LIMIT) -> str:
    if not value:
        return "None"
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _sort_relations(relations: Iterable[RelationDocument]) -> list[RelationDocument]:
    return sorted(relations, key=lambda rel: rel.metadata.created_at)


def _build_downstream_chain(tree: TreeDocument, node: NodeDocument) -> list[ChainStep]:
    relations_by_source: dict[str, list[RelationDocument]] = {}
    for relation in tree.relations:
        relations_by_source.setdefault(relation.source_id, []).append(relation)

    nodes = {item.id: item for item in tree.nodes}
    steps: list[ChainStep] = []
    current = node
    visited = {node.id}

    while len(steps) < MAX_CHAIN_LENGTH:
        options = _sort_relations(relations_by_source.get(current.id, []))
        if not options:
            break
        relation = options[0]
        effect = nodes.get(relation.target_id)
        cause = nodes.get(relation.source_id)
        if not cause or not effect:
            break
        steps.append(
            ChainStep(
                effect=effect,
                relation=relation,
                cause=cause,
                effect_validation_summary=summarize_validation_state(effect.validation),
            )
        )
        if relation.target_id in visited:
            break
        visited.add(relation.target_id)
        current = cause

    return steps


def _build_upstream_chain(tree: TreeDocument, node: NodeDocument) -> list[ChainStep]:
    relations_by_target: dict[str, list[RelationDocument]] = {}
    for relation in tree.relations:
        relations_by_target.setdefault(relation.target_id, []).append(relation)

    nodes = {item.id: item for item in tree.nodes}
    steps: list[ChainStep] = []
    current = node
    visited = {node.id}

    while len(steps) < MAX_CHAIN_LENGTH:
        options = _sort_relations(relations_by_target.get(current.id, []))
        if not options:
            break
        relation = options[0]
        effect = nodes.get(relation.target_id)
        cause = nodes.get(relation.source_id)
        if not effect or not cause:
            break
        steps.append(
            ChainStep(
                effect=effect,
                relation=relation,
                cause=cause,
                effect_validation_summary=summarize_validation_state(effect.validation),
            )
        )
        if relation.source_id in visited:
            break
        visited.add(relation.source_id)
        current = effect

    steps.reverse()
    return steps


def build_validation_prompt(tree: TreeDocument, node_id: str) -> ValidationPrompt:
    """Render validation prompt for selected node."""

    nodes_map = {item.id: item for item in tree.nodes}
    node = nodes_map.get(node_id)
    if node is None:
        raise KeyError(f"Node '{node_id}' not found in tree '{tree.id}'.")

    downstream = _build_downstream_chain(tree, node)
    steps = downstream or _build_upstream_chain(tree, node)

    lines: list[str] = [
        "System:",
        "You are an expert in the Theory of Constraints and causal analysis.",
        "Judge whether each causal link in a Current Reality Tree is well supported.",
        "Output JSON only, matching the schema provided.",
        "",
        "User:",
        "Context:",
        f"- Tree title: {truncate(tree.title)}",
        f'- Selected node: "{truncate(node.label)}"',
        f"- Chain length: {len(steps)} links",
        "",
        "Causal Chain (top -> bottom):",
    ]

    if not steps:
        lines.append("No causal relations were found for the selected node.")
    else:
        for index, step in enumerate(steps, start=1):
            lines.extend(
                [
                    f"Step {index}:",
                    f'- Effect node: "{truncate(step.effect.label)}"',
                    f'- Relation question: "{truncate(step.relation.question_label)}"',
                    f'- Cause node: "{truncate(step.cause.label)}"',
                    f'- Relation notes: "{truncate(step.relation.notes)}"',
                    f"- Existing validation: {truncate(step.effect_validation_summary)}",
                    "",
                ]
            )

    lines.extend(
        [
            "Task:",
            "1. Assess each link for logical plausibility and sufficiency given the information.",
            "2. Identify any assumptions, contradictions, or missing evidence.",
            "3. Provide an overall confidence score (0–100).",
            "4. Suggest up to 3 actionable questions or checks the user should consider.",
            "",
            "Output JSON schema:",
            "{",
            '  "confidence": number,',
            '  "verdict": "strong" | "uncertain" | "weak",',
            '  "observations": [',
            "    {",
            '      "link_index": number,',
            '      "assessment": string,',
            '      "severity": "info" | "warning" | "error"',
            "    }",
            "  ],",
            '  "suggested_questions": [string]',
            "}",
        ]
    )

    prompt = "\n".join(lines).strip()
    return ValidationPrompt(prompt=prompt, steps=steps, prompt_version=PROMPT_VERSION)
