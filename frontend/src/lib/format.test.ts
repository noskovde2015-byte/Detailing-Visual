import { describe, expect, it } from "vitest";

import { formatWhen, generationsCount, plural } from "./format";

describe("plural", () => {
  const forms = ["генерация", "генерации", "генераций"] as const;

  it.each([
    [1, "генерация"],
    [2, "генерации"],
    [4, "генерации"],
    [5, "генераций"],
    [11, "генераций"],
    [14, "генераций"],
    [21, "генерация"],
    [22, "генерации"],
    [111, "генераций"],
    [0, "генераций"],
  ])("%i → %s", (count, expected) => {
    expect(plural(count, forms)).toBe(expected);
  });

  it("собирает число со словом", () => {
    expect(generationsCount(61)).toBe("61 генерация");
  });
});

describe("formatWhen", () => {
  const now = new Date(2026, 9, 25, 18, 30);

  it("сегодня и вчера пишет словами", () => {
    expect(formatWhen(new Date(2026, 9, 25, 9, 5).toISOString(), now)).toBe("Сегодня, 09:05");
    expect(formatWhen(new Date(2026, 9, 24, 21, 47).toISOString(), now)).toBe("Вчера, 21:47");
  });

  it("раньше — датой", () => {
    expect(formatWhen(new Date(2026, 9, 20, 10, 15).toISOString(), now)).toMatch(/^20 октября/);
  });
});
