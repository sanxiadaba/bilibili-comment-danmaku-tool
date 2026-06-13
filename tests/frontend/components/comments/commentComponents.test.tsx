import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { CommentDetail } from "../../../../frontend/src/components/comments/CommentDetail";
import { CommentRow } from "../../../../frontend/src/components/comments/CommentRow";
import { CommentImages, CommentText } from "../../../../frontend/src/components/comments/CommentText";
import { flattenThread } from "../../../../frontend/src/lib/utils";
import { makeComment } from "../../helpers/factories";

describe("comment components", () => {
  it("renders emotes and normalized image URLs", () => {
    const comment = makeComment({
      message: "hi [doge]",
      pictures: [{ img_src: "//i.example/a.jpg", play_gif_thumbnail: true }],
      emote: {
        "[doge]": {
          url: "https://i.example/doge.png",
          jump_title: "doge",
          meta: { size: 2 },
        },
      },
    });

    const html = renderToStaticMarkup(
      <>
        <CommentText comment={comment} />
        <CommentImages comment={comment} compact />
      </>,
    );

    expect(html).toContain("hi ");
    expect(html).toContain("https://i.example/doge.png");
    expect(html).toContain("https://i.example/a.jpg");
    expect(html).toContain("GIF");
  });

  it("renders row badges, metadata and click wiring", () => {
    const onSelect = vi.fn();
    const comment = makeComment({
      is_deleted: true,
      is_up_owner: true,
      like: 12,
      message: "selected message",
      user: { mid: "42", uname: "Owner", avatar: "//i.example/avatar.jpg" },
    });

    const html = renderToStaticMarkup(<CommentRow active comment={comment} onSelect={onSelect} />);

    expect(html).toContain("Owner");
    expect(html).toContain("selected message");
    expect(html).toContain("12");
    expect(html).toContain("UP");
    expect(html).toContain("i.example/avatar.jpg");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("renders detail thread without exposing raw comment JSON", () => {
    const reply = makeComment({ rpid: "2", level: 2, message: "nested reply", user: { mid: "7", uname: "Bob" } });
    const comment = makeComment({ rpid: "1", message: "root comment", like: 9, rcount: 1 }, [reply]);

    const html = renderToStaticMarkup(
      <CommentDetail comment={comment} threadItems={flattenThread(comment)} onSelect={() => undefined} />,
    );

    expect(html).toContain("root comment");
    expect(html).toContain("nested reply");
    expect(html).toContain("rpid");
    expect(html).not.toContain("raw");
  });
});
