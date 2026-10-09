import { describe, expect, it } from "vitest";
import { sum } from "./math.js";

describe("sum", () => {
  it("adds numbers", () => {
    expect(sum([1, 2, 3])).toBe(6);
  });
  it("is 0 for an empty list", () => {
    expect(sum([])).toBe(0);
  });
});
