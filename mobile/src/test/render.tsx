/**
 * Minimal component-test harness.
 *
 * The project has no React Native testing library, so tests drive
 * `react-test-renderer` directly. Everything here is deliberately small: render
 * inside a fresh React Query client, find nodes by accessibility label or text,
 * and press them. Queries go through the accessibility tree on purpose — what a
 * VoiceOver user can find is what a test can find.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      // Mutations keep a garbage-collection timer alive too; without this the
      // Jest process lingers for the default five minutes after a test that
      // mutates.
      mutations: { retry: false, gcTime: 0 },
    },
  });
}

export interface RenderResult {
  renderer: ReactTestRenderer;
  client: QueryClient;
  unmount: () => Promise<void>;
}

export async function renderWithProviders(element: ReactElement): Promise<RenderResult> {
  const client = testQueryClient();
  let renderer!: ReactTestRenderer;
  await act(async () => {
    renderer = create(<QueryClientProvider client={client}>{element}</QueryClientProvider>);
  });
  return {
    renderer,
    client,
    unmount: async () => {
      await act(async () => {
        renderer.unmount();
      });
      client.clear();
    },
  };
}

/** Flush pending promises and effects. */
export async function settle(): Promise<void> {
  await act(async () => {
    // React Query batches observer notifications onto the next timer turn.
    // Waiting only for a resolved promise makes tests race under the full suite.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
}

function stringsIn(node: unknown, into: string[]): void {
  if (typeof node === "string") {
    into.push(node);
    return;
  }
  if (Array.isArray(node)) {
    for (const child of node) {
      stringsIn(child, into);
    }
    return;
  }
  if (node && typeof node === "object" && "children" in node) {
    stringsIn((node as { children: unknown }).children, into);
  }
}

/** All rendered text, joined — for "does the screen say this?" assertions. */
export function visibleText(renderer: ReactTestRenderer): string {
  const collected: string[] = [];
  stringsIn(renderer.toJSON(), collected);
  return collected.join("\n");
}

export function queryByLabel(
  renderer: ReactTestRenderer,
  label: string,
): ReactTestInstance | null {
  const matches = renderer.root.findAll(
    (node) => node.props?.accessibilityLabel === label,
    { deep: true },
  );
  return matches[0] ?? null;
}

export function getByLabel(renderer: ReactTestRenderer, label: string): ReactTestInstance {
  const found = queryByLabel(renderer, label);
  if (!found) {
    throw new Error(`No node with accessibility label "${label}".\n${visibleText(renderer)}`);
  }
  return found;
}

/** The innermost pressable/text node whose rendered string is exactly `text`. */
export function queryByText(renderer: ReactTestRenderer, text: string): ReactTestInstance | null {
  const matches = renderer.root.findAll(
    (node) => typeof node.props?.children === "string" && node.props.children === text,
    { deep: true },
  );
  return matches[matches.length - 1] ?? null;
}

/** Press the nearest ancestor (or self) that carries an `onPress` handler. */
export async function press(node: ReactTestInstance): Promise<void> {
  let current: ReactTestInstance | null = node;
  while (current && typeof current.props?.onPress !== "function") {
    current = current.parent ?? null;
  }
  if (!current) {
    throw new Error("Node has no pressable ancestor.");
  }
  const onPress = current.props.onPress as (event?: unknown) => void;
  await act(async () => {
    onPress({ nativeEvent: {} });
  });
}

export async function pressLabel(renderer: ReactTestRenderer, label: string): Promise<void> {
  await press(getByLabel(renderer, label));
}

export async function pressText(renderer: ReactTestRenderer, text: string): Promise<void> {
  const node = queryByText(renderer, text);
  if (!node) {
    throw new Error(`No pressable showing "${text}".\n${visibleText(renderer)}`);
  }
  await press(node);
}

export async function typeInto(node: ReactTestInstance, value: string): Promise<void> {
  const onChangeText = node.props.onChangeText as ((next: string) => void) | undefined;
  if (!onChangeText) {
    throw new Error("Node is not a text input.");
  }
  await act(async () => {
    onChangeText(value);
  });
}
