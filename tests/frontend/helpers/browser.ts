import { vi } from "vitest";

export function installWindowStub(url = "http://127.0.0.1:8000/") {
  const store = new Map<string, string>();
  const win = {
    location: new URL(url),
    localStorage: {
      clear: () => store.clear(),
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
    },
    history: {
      replaceState: (_state: unknown, _title: string, nextUrl: string) => {
        win.location = new URL(nextUrl, win.location.href);
      },
    },
  };
  vi.stubGlobal("window", win);
  return win;
}

export function installApiBrowserStubs(url = "http://127.0.0.1:8000/video/BV1xx411c7mD") {
  vi.stubGlobal("window", {
    location: new URL(url),
  });
  vi.stubGlobal("navigator", {
    sendBeacon: vi.fn(() => true),
  });
  vi.stubGlobal("performance", {
    now: vi.fn(() => 100),
  });
}
