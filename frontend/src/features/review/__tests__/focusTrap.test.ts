import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { trapTab } from "../focusTrap";

function setup() {
  document.body.innerHTML = `<div id="box"><h2 tabindex="-1" id="heading">Title</h2><button id="first">First</button><input id="middle" /><button id="last">Last</button><button id="off" disabled>Off</button></div>`;
  const get = (id: string) => document.getElementById(id) as HTMLElement;
  const press = (shiftKey: boolean) => {
    let prevented = false;
    trapTab({ shiftKey, preventDefault: () => { prevented = true; } } as unknown as ReactKeyboardEvent, get("box"));
    return prevented;
  };
  return { get, press };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("020-FR-052 Tab stays inside a review dialog", () => {
  it("020-FR-052 Tab on the last control goes to the first, and elsewhere is left alone", () => {
    const { get, press } = setup();

    get("last").focus();
    expect(press(false)).toBe(true);
    expect(get("first")).toHaveFocus();
    get("middle").focus();
    expect(press(false)).toBe(false);
  });

  it("020-FR-052 Shift+Tab on the first control, or on the heading that is not in the tab order, goes to the last", () => {
    const { get, press } = setup();

    get("first").focus();
    expect(press(true)).toBe(true);
    expect(get("last")).toHaveFocus();
    get("heading").focus();
    expect(press(true)).toBe(true);
    expect(get("last")).toHaveFocus();
    get("middle").focus();
    expect(press(true)).toBe(false);
  });

  it("020-FR-052 with every control disabled, Tab and Shift+Tab keep focus on the container and do not throw", () => {
    document.body.innerHTML = `<div id="box" tabindex="-1"><button id="only" disabled>Only</button></div>`;
    const box = document.getElementById("box") as HTMLElement;
    for (const shiftKey of [false, true]) {
      let prevented = false;
      expect(() => trapTab({ shiftKey, preventDefault: () => { prevented = true; } } as unknown as ReactKeyboardEvent, box)).not.toThrow();
      expect(prevented).toBe(true);
      expect(box).toHaveFocus();
    }
  });
});
