import {
  historyPageUrl,
  ownedPresentationKey,
  sourceChatHref,
  projectHistoryHref,
} from "@/sections/workspace/presentations/history";

describe("presentation history navigation and requests", () => {
  test("uses the verified private chat route and rejects unsafe IDs", () => {
    const id = "12345678-1234-1234-1234-123456789abc";
    expect(sourceChatHref(id)).toBe(`/app?chatId=${id}`);
    expect(sourceChatHref("../admin")).toBeNull();
    expect(sourceChatHref(null)).toBeNull();
  });
  test("uses the verified project route only for positive integer IDs", () => {
    expect(projectHistoryHref(7)).toBe("/app?projectId=7");
    expect(projectHistoryHref(-1)).toBeNull();
    expect(projectHistoryHref(1.2)).toBeNull();
  });
  test("fetches a bounded page plus lookahead and includes server status filter", () => {
    expect(historyPageUrl(0, "all")).toBe(
      "/api/orgmesh/presenton/history?limit=21&offset=0"
    );
    expect(historyPageUrl(2, "error")).toBe(
      "/api/orgmesh/presenton/history?limit=21&offset=40&status=error"
    );
  });
  test("isolates cached data by resolved owner and waits for user resolution", () => {
    expect(ownedPresentationKey("/api/x", undefined)).toBeNull();
    expect(ownedPresentationKey("/api/x", "owner-a")).not.toEqual(
      ownedPresentationKey("/api/x", "owner-b")
    );
  });
});

test("rejects offsets outside the backend pagination bound", () => {
  expect(() => historyPageUrl(-1, "all")).toThrow(RangeError);
  expect(() => historyPageUrl(5001, "all")).toThrow(RangeError);
  expect(() => historyPageUrl(Number.NaN, "all")).toThrow(RangeError);
});
