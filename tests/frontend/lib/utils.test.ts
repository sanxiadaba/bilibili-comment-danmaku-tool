import { describe, expect, it } from "vitest";
import {
  filterComments,
  flattenThread,
  getCommentPictures,
  getCommentTextParts,
  locationBuckets,
  sortComments,
  topAuthors,
  topLiked,
} from "../../../frontend/src/lib/utils";
import { makeComment } from "../helpers/factories";

describe("comment utilities", () => {
  it("sorts comments by likes, replies and time with stable tie-breakers", () => {
    const comments = [
      makeComment({ rpid: "1", like: 1, rcount: 1, ctime: 100 }),
      makeComment({ rpid: "2", like: 5, rcount: 2, ctime: 90 }),
      makeComment({ rpid: "3", like: 5, rcount: 1, ctime: 120 }),
    ];

    expect(sortComments(comments, "like_desc").map((item) => item.normalized.rpid)).toEqual(["3", "2", "1"]);
    expect(sortComments(comments, "reply_desc").map((item) => item.normalized.rpid)).toEqual(["2", "3", "1"]);
    expect(sortComments(comments, "time_asc").map((item) => item.normalized.rpid)).toEqual(["2", "1", "3"]);
  });

  it("filters comments by text, author, level, owner, location and minimum likes", () => {
    const comments = [
      makeComment({
        rpid: "1",
        level: 1,
        message: "first message",
        like: 10,
        ip_location: "Shanghai",
        is_up_owner: true,
        user: { mid: "42", uname: "owner" },
      }),
      makeComment({
        rpid: "2",
        level: 2,
        message: "nested reply",
        like: 2,
        ip_location: "Beijing",
        user: { mid: "7", uname: "bob" },
      }),
    ];

    expect(filterComments(comments, "owner", "all", "all", 0).map((item) => item.normalized.rpid)).toEqual(["1"]);
    expect(filterComments(comments, "", "reply", "all", 0).map((item) => item.normalized.rpid)).toEqual(["2"]);
    expect(filterComments(comments, "", "owner", "all", 0).map((item) => item.normalized.rpid)).toEqual(["1"]);
    expect(filterComments(comments, "", "all", "Shanghai", 0).map((item) => item.normalized.rpid)).toEqual(["1"]);
    expect(filterComments(comments, "", "all", "all", 5).map((item) => item.normalized.rpid)).toEqual(["1"]);
  });

  it("splits emotes, normalizes pictures, aggregates authors and flattens threads", () => {
    const reply = makeComment({ rpid: "2", level: 2, message: "reply", mid: "7", user: { mid: "7", uname: "bob" } });
    const comment = makeComment(
      {
        rpid: "1",
        message: "hi [doge] end",
        like: 8,
        pictures: [{ img_src: "//i.example/a.jpg" }, { img_src: "" }],
        emote: {
          "[doge]": {
            url: "http://i.example/doge.png",
            jump_title: "doge",
            meta: { size: 1 },
          },
        },
      },
      [reply],
    );

    expect(getCommentTextParts(comment.normalized).map((part) => part.type)).toEqual(["text", "emote", "text"]);
    expect(getCommentPictures(comment)).toEqual([{ img_src: "https://i.example/a.jpg" }]);
    expect(locationBuckets([comment, reply]).reduce((sum, item) => sum + item.count, 0)).toBe(2);
    expect(topAuthors([comment, reply]).map((item) => item.name)).toEqual(["alice", "bob"]);
    expect(topLiked([reply, comment])[0].normalized.rpid).toBe("1");
    expect(flattenThread(comment).map((item) => item.rpid)).toEqual(["1", "2"]);
  });
});
