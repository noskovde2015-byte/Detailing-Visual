import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, request } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("на 401 один раз обновляет сессию и повторяет запрос", async () => {
    let authorized = false;
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/auth/refresh") {
        authorized = true;
        return json(204, null);
      }
      return authorized ? json(200, { ok: url }) : json(401, { detail: "no" });
    });
    vi.stubGlobal("fetch", fetchMock);

    // Три параллельных запроса — refresh должен уйти ровно один.
    const results = await Promise.all([request("/api/a"), request("/api/b"), request("/api/c")]);

    expect(results).toEqual([{ ok: "/api/a" }, { ok: "/api/b" }, { ok: "/api/c" }]);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/auth/refresh")).toHaveLength(1);
  });

  it("если refresh не удался — отдаёт 401 без повтора", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      url === "/api/auth/refresh" ? json(401, {}) : json(401, { detail: "Не авторизован" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/api/users/me")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("достаёт текст ошибки из detail, включая 402 с объектом", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => json(402, { detail: { message: "Недостаточно генераций на балансе", balance: 0 } })),
    );

    const error = await request("/api/generations").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Недостаточно генераций на балансе");
    expect((error as ApiError).detail).toMatchObject({ balance: 0 });
  });
});
