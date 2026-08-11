// Allure Report 3 configuration for the aggregate CI report.
//
// `maxFailures: 0` is the whole feature: `allure quality-gate` fails the
// `allure-report` job when the aggregate contains any failed or broken result,
// which the job previously published without ever judging.
//
// ASK class (scripts/classify_path_risk.py), because this file decides what
// "passing" means. The answer to a failing gate is never to raise the number.
//
// No import of Allure's `defineConfig`: it is an identity function, and the
// repository root has no node_modules -- the CLI is installed under frontend/.
export default {
  name: "BrainBuddy CI",
  qualityGate: {
    rules: [{ maxFailures: 0 }],
  },
};
