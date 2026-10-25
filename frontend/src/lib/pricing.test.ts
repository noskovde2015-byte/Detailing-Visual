import { describe, expect, it } from "vitest";

import { PACKS, pricePerGeneration } from "./pricing";

describe("пакеты", () => {
  it("минимальная цена — 59 ₽ за генерацию в самом маленьком пакете", () => {
    expect(pricePerGeneration(PACKS[0]!)).toBe(59);
  });

  it("чем больше пакет, тем дешевле генерация", () => {
    const prices = PACKS.map(pricePerGeneration);
    expect([...prices].sort((a, b) => b - a)).toEqual(prices);
  });

  it("обещанная выгода в бейдже совпадает с расчётом", () => {
    const base = pricePerGeneration(PACKS[0]!);
    for (const pack of PACKS) {
      const match = pack.badge?.match(/Выгода (\d+)%/);
      if (!match) continue;
      const saving = Math.round((1 - pack.price / pack.count / base) * 100);
      expect(saving).toBe(Number(match[1]));
    }
  });
});
