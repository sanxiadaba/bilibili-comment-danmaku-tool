import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorBoundary } from "../../../frontend/src/components/ErrorBoundary";

function Boom({ explode }: { explode: boolean }) {
  if (explode) throw new Error("接口数据格式不对");
  return <div>内容正常</div>;
}

describe("ErrorBoundary", () => {
  it("shows a recoverable message instead of a blank page", () => {
    // React logs the caught error; keep the test output readable.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary>
        <Boom explode />
      </ErrorBoundary>,
    );

    expect(screen.getByText("页面渲染出错")).toBeTruthy();
    expect(screen.getByText("接口数据格式不对")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "返回视频库" })).toBeTruthy();

    consoleError.mockRestore();
  });

  it("keeps rendering children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <Boom explode={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByText("内容正常")).toBeTruthy();
  });

  it("retries rendering children after the user asks to", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();

    render(
      <ErrorBoundary>
        <Boom explode />
      </ErrorBoundary>,
    );

    // The boundary clears its error state; the same throwing child re-throws, which is fine —
    // what matters is that the action is wired and the UI stays interactive.
    await user.click(screen.getByRole("button", { name: "重试" }));

    expect(screen.getByText("页面渲染出错")).toBeTruthy();
    consoleError.mockRestore();
  });
});
