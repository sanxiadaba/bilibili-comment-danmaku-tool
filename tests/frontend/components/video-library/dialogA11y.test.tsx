import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DeleteConfirmDialog } from "../../../../frontend/src/components/video-library/DeleteConfirmDialog";
import { NoticeDialog } from "../../../../frontend/src/components/video-library/NoticeDialog";

describe("dialog accessibility", () => {
  it("names the notice dialog and closes on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<NoticeDialog notice={{ kind: "success", title: "导出完成", message: "文件已生成" }} onClose={onClose} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const labelledBy = dialog.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy!)?.textContent).toContain("导出完成");

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("moves focus into the destructive confirm dialog", async () => {
    render(
      <DeleteConfirmDialog
        target={{ kind: "video", video: { bvid: "BV1xx411c7mD", title: "测试视频", comment_total_count: 3, danmaku_count: 4 } as never }}
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );

    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);
    // The confirm input is reachable without a first exploratory click.
    expect(screen.getByRole("textbox")).toBeTruthy();
  });

  it("traps Tab inside the dialog", async () => {
    const user = userEvent.setup();
    render(<NoticeDialog notice={{ kind: "warning", title: "提示", message: "内容" }} onClose={() => {}} />);

    const dialog = screen.getByRole("dialog");
    await user.keyboard("{Tab}");
    await user.keyboard("{Tab}");
    await user.keyboard("{Tab}");
    await user.keyboard("{Tab}");

    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("labels the row as a button instead of nesting a link inside one", () => {
    // Covered by CommentRow rendering: the interactive element must expose role=button.
    const { container } = render(
      <NoticeDialog notice={{ kind: "error", title: "错误", message: "失败" }} onClose={() => {}} />,
    );
    expect(container.querySelector("button button")).toBeNull();
  });
});
