// Global test setup. Importing jest-dom registers matchers like toBeInTheDocument on
// vitest's expect; it's DOM-free at import time, so it's safe for the node-env pure
// tests too. Component tests add `// @vitest-environment jsdom` for a real DOM.
import "@testing-library/jest-dom/vitest";
