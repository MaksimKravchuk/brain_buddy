/**
 * A controllable stand-in for expo-router's navigation surface.
 *
 * Navigation is a device concern: the tests here assert *what a screen asks
 * for*, not that a native stack honoured it. The mock records those requests
 * and lets a test set the route params a screen was opened with.
 *
 * Installed once in `jest.setup.js`, so every suite shares the same instance
 * within its own module registry; `resetRouter()` runs between tests.
 */

export interface RouterSpy {
  push: jest.Mock;
  replace: jest.Mock;
  back: jest.Mock;
  dismissAll: jest.Mock;
  navigate: jest.Mock;
  setParams: jest.Mock;
}

const router: RouterSpy = {
  push: jest.fn(),
  replace: jest.fn(),
  back: jest.fn(),
  dismissAll: jest.fn(),
  navigate: jest.fn(),
  setParams: jest.fn(),
};

let searchParams: Record<string, string | undefined> = {};
let pathname = "/";
let segments: string[] = [];
const redirects: string[] = [];

/** The router every screen under test received. */
export function routerSpy(): RouterSpy {
  return router;
}

/** Route params for the next render, as `useLocalSearchParams` returns them. */
export function setSearchParams(params: Record<string, string | undefined>): void {
  searchParams = params;
}

export function setPathname(next: string): void {
  pathname = next;
  segments = next.split("/").filter(Boolean);
}

/** Targets of every `<Redirect href=… />` rendered so far. */
export function renderedRedirects(): string[] {
  return [...redirects];
}

export function resetRouter(): void {
  for (const spy of Object.values(router)) {
    spy.mockReset();
  }
  searchParams = {};
  redirects.length = 0;
  setPathname("/");
}

/** The module object jest substitutes for `expo-router`. */
export function expoRouterMock() {
  const React = require("react");
  const { View } = require("react-native");

  function Redirect({ href }: { href: string }) {
    redirects.push(String(href));
    return React.createElement(View, { testID: `redirect-${String(href)}` });
  }

  const Stack = ({ children }: { children?: unknown }) =>
    React.createElement(View, { testID: "stack" }, children);
  Stack.Screen = () => null;

  return {
    __esModule: true,
    router,
    useRouter: () => router,
    usePathname: () => pathname,
    useSegments: () => segments,
    useLocalSearchParams: () => searchParams,
    useGlobalSearchParams: () => searchParams,
    useFocusEffect: (callback: () => void) => React.useEffect(callback, [callback]),
    Redirect,
    Stack,
    Link: ({ children }: { children?: unknown }) =>
      React.createElement(View, { testID: "link" }, children),
  };
}
