// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../state/useBackendHealth", () => ({ useBackendHealth: vi.fn() }));
import { useBackendHealth } from "../state/useBackendHealth";
import { BackendBanner } from "./BackendBanner";

describe("BackendBanner", () => {
  afterEach(() => vi.clearAllMocks());

  it("renders nothing while the backend is healthy", () => {
    vi.mocked(useBackendHealth).mockReturnValue(true);
    const { container } = render(<BackendBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows an alert when the backend is unreachable", () => {
    vi.mocked(useBackendHealth).mockReturnValue(false);
    render(<BackendBanner />);
    const alert = screen.getByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(/backend/i);
  });
});
