# Research: Flexible Relation Linking

## Decisions and Rationale

- **Decision**: Keep direction semantics as cause (lower) → effect (upper) for all relations, including cross-branch links.  
  **Rationale**: Preserves consistent reasoning paths and aligns with existing canvas semantics.  
  **Alternatives considered**: Allow arbitrary direction (rejected: breaks causality meaning), infer direction by depth (rejected: brittle and confusing).

- **Decision**: Block self-links, duplicate links, and cycle-closing links with inline, human-readable errors plus correlation references.  
  **Rationale**: Protects graph integrity and debuggability without breaking the user flow.  
  **Alternatives considered**: Allow duplicates with warnings (rejected: clutter and ambiguity); modal errors (rejected: disrupts flow).

- **Decision**: Persist new relations across save/reload and export/import with direction intact.  
  **Rationale**: Ensures sharing and recovery keep reasoning structure stable.  
  **Alternatives considered**: Mark cross-branch relations as ephemeral (rejected: violates user goals).

- **Decision**: Accessibility for blocked-link feedback: focus the inline message and announce via live region.  
  **Rationale**: Provides usable feedback for keyboard and screen reader users without modal interruptions.  
  **Alternatives considered**: Toast-only (rejected: insufficient for keyboard/AT users); focus-only (rejected: lacks announcement).
