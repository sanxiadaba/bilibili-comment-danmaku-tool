export const sortLabels = {
  time_asc: "时间升序",
  time_desc: "时间降序",
  like_desc: "点赞优先",
  reply_desc: "回复优先",
} as const;

export function getBilibiliUserUrl(mid?: string) {
  return mid ? `https://space.bilibili.com/${mid}` : undefined;
}
