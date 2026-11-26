import { describe, expect, it } from "vitest";
import {
  coarsenBuckets,
  filterComments,
  flattenThread,
  getCommentPictures,
  getCommentTextParts,
  hourlyBuckets,
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

  it("ignores malformed time_iso values instead of throwing", () => {
    const comments = [
      makeComment({ rpid: "bad", time_iso: "not-a-date" }),
      makeComment({ rpid: "ok", time_iso: "2024-01-01T00:00:00+08:00" }),
    ];

    expect(() => hourlyBuckets(comments)).not.toThrow();
    expect(hourlyBuckets(comments)).toHaveLength(1);
  });

  it("coarsens filtered buckets with the all-buckets day granularity", () => {
    const comments = Array.from({ length: 200 }, (_, index) =>
      makeComment({
        rpid: String(index),
        ctime: 1700000000 + index * 3600,
        time_iso: new Date(Date.UTC(2024, 0, 1) + index * 3600_000).toISOString(),
      }),
    );

    const allBuckets = coarsenBuckets(hourlyBuckets(comments));
    expect(allBuckets.length).toBeLessThanOrEqual(180);
    expect(allBuckets.every((bucket) => new Date(bucket.timestamp).getHours() === 0)).toBe(true);

    const filteredBuckets = coarsenBuckets(hourlyBuckets(comments.slice(0, 10)), 180, "day");
    expect(filteredBuckets.length).toBeGreaterThan(0);
    expect(filteredBuckets.every((bucket) => new Date(bucket.timestamp).getHours() === 0)).toBe(true);
  });
});
