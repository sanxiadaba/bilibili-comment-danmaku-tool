import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { VirtualList } from "../../../../frontend/src/components/ui/VirtualList";

// jsdom has no layout, so give the scroll container a measurable viewport.
Object.defineProperty(HTMLElement.prototype, "clientHeight", {
  configurable: true,
  get() {
    return 400;
  },
});

function makeItems(count: number) {
  return Array.from({ length: count }, (_, index) => ({ id: `item-${index}`, label: `条目 ${index}` }));
}

function renderList(items: { id: string; label: string }[]) {
  return render(
    <VirtualList
      className="list"
      empty={<div>没有数据</div>}
      estimateSize={40}
      getKey={(item) => item.id}
      items={items}
      overscan={6}
      renderItem={(item) => (
        <div data-testid="row" key={item.id}>
          {item.label}
        </div>
      )}
    />,
  );
}

describe("VirtualList", () => {
  it("only renders a window of a long list", () => {
    renderList(makeItems(200));

    const rows = screen.getAllByTestId("row");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(60);
    expect(screen.getByText("条目 0")).toBeTruthy();
    expect(screen.queryByText("条目 199")).toBeNull();
  });

  it("renders the empty state", () => {
    renderList([]);

    expect(screen.getByText("没有数据")).toBeTruthy();
  });

  it("measures its viewport when items arrive after an empty first render", () => {
    const { rerender } = renderList([]);

    rerender(
      <VirtualList
        className="list"
        empty={<div>没有数据</div>}
        estimateSize={40}
        getKey={(item) => item.id}
        items={makeItems(200)}
        overscan={6}
        renderItem={(item) => (
          <div data-testid="row" key={item.id}>
            {item.label}
          </div>
        )}
      />,
    );

    // A measured 400px viewport plus overscan renders well past the 13-row floor the old
    // never-measured container produced.
    expect(screen.getAllByTestId("row").length).toBeGreaterThan(13);
  });
});
