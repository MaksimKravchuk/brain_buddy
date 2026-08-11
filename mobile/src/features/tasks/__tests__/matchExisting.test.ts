/**
 * 006-FR-005 — a typed name that matches an existing project or Tag must offer
 * that one rather than create a duplicate.
 *
 * The table mirrors the server's own uniqueness rule
 * (`normalize_task_name` in backend/app/modules/tasks/repository.py: NFKC →
 * trim → collapse internal whitespace → case-fold). A client rule narrower than
 * the server's does not merely miss an offer: the person taps "Create" and the
 * server answers 409.
 */

import { matchExisting, type NamedEntity } from "../matchExisting";

const PROJECTS: NamedEntity[] = [
  { id: "project_1", name: "Q3 Launch" },
  { id: "project_2", name: "Onboarding drop-off" },
  { id: "project_3", name: "Inbox" },
  { id: "project_4", name: "Finance" },
];

const Q3 = PROJECTS[0];

describe("006-FR-005 matchExisting offers an existing entity instead of a duplicate", () => {
  it.each<[string, string, NamedEntity | null]>([
    ["exact", "Q3 Launch", Q3],
    ["case difference, lowered", "q3 launch", Q3],
    ["case difference, raised", "Q3 LAUNCH", Q3],
    ["leading whitespace", "   Q3 Launch", Q3],
    ["trailing whitespace", "Q3 Launch   ", Q3],
    ["leading and trailing whitespace", "  Q3 Launch  ", Q3],
    ["tab and newline padding", "\tQ3 Launch\n", Q3],
    ["collapsed internal whitespace, as the server collapses it", "Q3   Launch", Q3],
    ["case and whitespace together", "  q3   LAUNCH ", Q3],
    ["NFKC-equivalent characters", "Ｑ３ Launch", Q3],
    ["another exact name in the list", "Inbox", PROJECTS[2]],
  ])("%s matches: %s", (_why, typed, expected) => {
    expect(matchExisting(typed, PROJECTS)).toEqual(expected);
  });

  it.each<[string, string]>([
    ["a prefix of an existing name", "Q3"],
    ["a suffix of an existing name", "Launch"],
    ["an interior substring", "boarding"],
    ["a single shared character", "Q"],
    ["the existing name plus more words", "Q3 Launch retrospective"],
    ["a name that merely starts the same", "Inboxes"],
    ["internal punctuation removed", "Onboarding dropoff"],
  ])("%s must NOT match, so the person can still create it: %s", (_why, typed) => {
    expect(matchExisting(typed, PROJECTS)).toBeNull();
  });

  it("006-FR-005 returns the whole candidate, so the caller can attach it by id", () => {
    const match = matchExisting("q3 launch", PROJECTS);
    expect(match).not.toBeNull();
    expect(match?.id).toBe("project_1");
    expect(match?.name).toBe("Q3 Launch");
  });

  it("006-FR-005 matches an NFKC-equivalent ligature, as the server would", () => {
    // "ﬁnance" normalizes to "finance"; the server would reject the create.
    expect(matchExisting("ﬁnance", PROJECTS)).toEqual(PROJECTS[3]);
  });

  it.each([["empty", ""], ["whitespace only", "   "], ["a newline", "\n"]])(
    "006-FR-005 %s input is not a match: nothing was typed",
    (_why, typed) => {
      expect(matchExisting(typed, PROJECTS)).toBeNull();
    },
  );

  it("006-FR-005 returns null against an empty list, so a first-run create is offered", () => {
    expect(matchExisting("Q3 Launch", [])).toBeNull();
  });

  it("006-FR-005 is deterministic when the list already holds two equal names", () => {
    const duplicated: NamedEntity[] = [
      { id: "tag_1", name: "home" },
      { id: "tag_2", name: "Home" },
    ];
    expect(matchExisting("HOME", duplicated)).toEqual(duplicated[0]);
  });

  it("006-FR-005 ignores a candidate with a blank name rather than matching blank input", () => {
    const withBlank: NamedEntity[] = [{ id: "tag_blank", name: "  " }, ...PROJECTS];
    expect(matchExisting("  ", withBlank)).toBeNull();
  });
});

describe("006-FR-005 Tag names, where the server strips one leading @", () => {
  const TAGS: NamedEntity[] = [
    { id: "tag_1", name: "home" },
    { id: "tag_2", name: "deep work" },
  ];

  it("matches a typed @home against the existing home Tag when asked to", () => {
    // `normalize_task_name(..., strip_tag_prefix=True)` — creating "@home"
    // server-side would collide with "home" and 409.
    expect(matchExisting("@home", TAGS, { stripTagPrefix: true })).toEqual(TAGS[0]);
  });

  it("leaves the @ alone for projects, which the server does not strip", () => {
    expect(matchExisting("@home", TAGS)).toBeNull();
  });

  it("strips only one @ and the whitespace behind it, as the server does", () => {
    expect(matchExisting("@ deep work", TAGS, { stripTagPrefix: true })).toEqual(TAGS[1]);
    expect(matchExisting("@@home", TAGS, { stripTagPrefix: true })).toBeNull();
  });
});
