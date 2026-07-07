import { describe, expect, it } from "vitest";

import { greeting, timeBucket } from "./greeting";

describe("timeBucket", () => {
  it("maps hours to buckets", () => {
    expect(timeBucket(7)).toBe("morning");
    expect(timeBucket(14)).toBe("afternoon");
    expect(timeBucket(19)).toBe("evening");
    expect(timeBucket(1)).toBe("late");
    expect(timeBucket(23)).toBe("late");
  });
});

describe("greeting", () => {
  it("includes the first name only", () => {
    expect(greeting("Mohammed Lubbad", 1, 0)).toBe("Up late, Mohammed?");
    expect(greeting("Mohammed", 8, 0)).toBe("Good morning, Mohammed");
  });

  it("reads naturally without a name", () => {
    expect(greeting("", 8, 0)).toBe("Good morning");
    expect(greeting(undefined, 1, 0)).toBe("Up late?");
  });

  it("varies by seed within a bucket", () => {
    const a = greeting("Sam", 8, 0);
    const b = greeting("Sam", 8, 1);
    expect(a).not.toBe(b);
  });
});
