/**
 * Shared unit-test environment for the mobile app.
 *
 * Only device/native boundaries are stubbed here, and each is stubbed with the
 * mock its own package ships wherever one exists. Product modules are never
 * mocked globally — a test that needs one faked does it itself, in view of the
 * reader.
 */

// The insets provider is a native module; its own mock returns zero insets.
// That mock is authored as an ES default export, hence the interop unwrap.
jest.mock("react-native-safe-area-context", () => {
  const mock = require("react-native-safe-area-context/jest/mock");
  return mock.default ?? mock;
});

// Device key/value store, backed by an in-memory map.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

// Navigation is a device concern; the mock records what a screen asked for.
jest.mock("expo-router", () => require("./src/test/expoRouterMock").expoRouterMock());

// jest-expo's auto-mock of this native module returns undefined for
// randomUUID, which would send `Idempotency-Key: undefined` on every mutation.
jest.mock("expo-crypto", () => require("./src/test/expoCryptoMock").expoCryptoMock());

// Gesture handler installs a JSI binding at import time; its own jest setup
// replaces that with JS stand-ins.
require("react-native-gesture-handler/jestSetup");

// The recorder and the file system are the two device boundaries the brain
// dump drives; both stand-ins record the call sequence the product code made.
jest.mock("expo-audio", () => require("./src/test/expoAudioMock").expoAudioMock());
jest.mock("expo-file-system", () => require("./src/test/expoFileSystemMock").expoFileSystemMock());

beforeEach(() => {
  require("./src/test/expoRouterMock").resetRouter();
  require("./src/test/expoCryptoMock").resetUuids();
  require("./src/test/expoAudioMock").resetAudio();
  require("./src/test/expoFileSystemMock").resetFileSystem();
});

// Icons render as host views; the glyphs carry no behaviour worth asserting.
jest.mock("lucide-react-native", () => {
  const React = require("react");
  const { View } = require("react-native");
  return new Proxy(
    {},
    {
      get: (_target, name) => {
        if (name === "__esModule") {
          return true;
        }
        const Icon = (props) => React.createElement(View, { ...props, testID: `icon-${String(name)}` });
        Icon.displayName = String(name);
        return Icon;
      },
    },
  );
});

// Allure taxonomy defaults. Registered last so its afterEach runs after the
// device stubs are in place; it fills the epic/feature/story and step evidence
// that `scripts/validate_allure_taxonomy.py` requires of every result.
require("./src/test/allureTaxonomy").registerAllureTaxonomy();
