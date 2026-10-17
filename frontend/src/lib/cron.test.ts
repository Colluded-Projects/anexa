import { describe, expect, it } from "vitest";
import { describeCron, validateCron } from "./cron";

describe("validateCron", () => {
  it.each(["* * * * *", "*/15 * * * *", "0 9 * * 1-5", "30 8,17 1 JAN,jul mon", "0 0 1-15/2 * 7"])(
    "accepts %s",
    (expression) => {
      expect(validateCron(expression)).toBeNull();
    },
  );

  it("requires exactly five fields", () => {
    expect(validateCron("0 9 * *")).toMatch(/5 fields.*got 4/);
    expect(validateCron("0 0 9 * * *")).toMatch(/got 6/);
    expect(validateCron("")).toMatch(/got 0/);
  });

  it("rejects out-of-range values and names the field", () => {
    expect(validateCron("60 * * * *")).toMatch(/Minute must be 0-59/);
    expect(validateCron("0 24 * * *")).toMatch(/Hour/);
    expect(validateCron("0 0 0 * *")).toMatch(/Day of month/);
    expect(validateCron("0 0 * 13 *")).toMatch(/Month/);
    expect(validateCron("0 0 * * 8")).toMatch(/Day of week/);
  });

  it("rejects malformed steps, ranges and junk", () => {
    expect(validateCron("*/0 * * * *")).toMatch(/step/i);
    expect(validateCron("5-1 * * * *")).toMatch(/backwards/);
    expect(validateCron("abc * * * *")).not.toBeNull();
    expect(validateCron("1,,2 * * * *")).not.toBeNull();
  });
});

describe("describeCron", () => {
  it.each([
    ["* * * * *", "Every minute"],
    ["*/15 * * * *", "Every 15 minutes"],
    ["0 * * * *", "Every hour"],
    ["30 * * * *", "Every hour at minute 30"],
    ["0 */6 * * *", "Every 6 hours"],
    ["0 9 * * *", "Every day at 09:00"],
    ["5 14 * * 1", "At 14:05 on Monday"],
    ["0 9 * * 1-5", "At 09:00 on Monday through Friday"],
    ["0 9 * * MON,WED", "At 09:00 on Monday and Wednesday"],
    ["0 0 1 * *", "At 00:00 on day 1 of the month"],
    ["0 8,17 * * *", "Every day at 08:00 and 17:00"],
    ["0 0 1 1 *", "At 00:00 on day 1 of the month, in January"],
    ["0 9 * * 7", "At 09:00 on Sunday"],
  ])("%s → %s", (expression, expected) => {
    expect(describeCron(expression)).toBe(expected);
  });

  it("returns an empty string for an invalid expression", () => {
    expect(describeCron("nope")).toBe("");
  });
});
