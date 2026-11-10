import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// React Testing Library does not auto-cleanup without the jest globals.
afterEach(() => {
  cleanup();
});

// jsdom has no layout engine; components that virtualize need a measurable viewport.
if (!("ResizeObserver" in globalThis)) {
  class TestResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  // @ts-expect-error - test shim
  globalThis.ResizeObserver = TestResizeObserver;
}

if (!("requestAnimationFrame" in globalThis)) {
  globalThis.requestAnimationFrame = ((callback: FrameRequestCallback) =>
    setTimeout(() => callback(performance.now()), 0) as unknown as number) as typeof requestAnimationFrame;
  globalThis.cancelAnimationFrame = ((handle: number) => clearTimeout(handle)) as typeof cancelAnimationFrame;
}
