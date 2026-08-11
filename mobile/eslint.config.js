/** CommonJS because the package is not `"type": "module"` — unlike frontend/eslint.config.js. */
const { defineConfig } = require("eslint/config");
const expoConfig = require("eslint-config-expo/flat");

module.exports = defineConfig([
  {
    ignores: ["coverage", "dist", ".expo", "android", "ios"]
  },
  ...expoConfig,
  {
    // Every rule eslint-config-expo 57 ships is enforced, including the React
    // Compiler-era ones. `react-hooks/refs` and `react-hooks/set-state-in-effect`
    // were deferred when the linter was introduced and are now satisfied by the
    // product code: `useAnimatedValue` replaces the
    // `useRef(new Animated.Value(0)).current` idiom, and `useServerDraft` plus
    // per-session remounting replace the effects that re-synced state. Nothing
    // is turned down here — do not start a list.
    files: ["**/*.{ts,tsx}"],
    settings: {
      // eslint-config-expo's core config enables the tsconfig resolver, then its
      // own top-level object replaces `import/resolver` wholesale with a node-only
      // one. Restore it here or every `@/…` import reports import/no-unresolved.
      "import/resolver": {
        typescript: true,
        node: { extensions: [".js", ".jsx", ".ts", ".tsx", ".json"] }
      }
    }
  },
  {
    // Jest's globals are injected by the runner, and its module factories have
    // to `require` lazily — neither is visible to the linter's flat config.
    // Scoped to test code only; product code keeps the stricter defaults.
    files: [
      "jest.setup.js",
      "src/test/**/*.{ts,tsx}",
      "src/**/__tests__/**/*.{ts,tsx}"
    ],
    languageOptions: {
      globals: {
        jest: "readonly",
        describe: "readonly",
        it: "readonly",
        test: "readonly",
        expect: "readonly",
        beforeAll: "readonly",
        beforeEach: "readonly",
        afterAll: "readonly",
        afterEach: "readonly"
      }
    },
    rules: {
      "@typescript-eslint/no-require-imports": "off",
      // The router stand-in returns component factories, which have no
      // meaningful display name to give.
      "react/display-name": "off"
    }
  }
]);
