/**
 * HTTP-клиент к нашему API.
 *
 * Авторизация на httpOnly-cookie: токены JS не видит. Короткоживущий access-токен
 * истекает раз в полчаса, тогда API отвечает 401 — клиент один раз вызывает
 * /api/auth/refresh и повторяет запрос. Параллельные запросы ждут один и тот же
 * refresh, а не запускают свои: иначе ротация refresh-токена выбьет сессию.
 */

export type ValidationIssue = { loc: (string | number)[]; msg: string; type: string };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown) {
    super(describeDetail(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function describeDetail(status: number, detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as Partial<ValidationIssue> | undefined;
    if (first?.msg) return first.msg;
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message: unknown }).message;
    if (typeof message === "string") return message;
  }
  if (status >= 500) return "Сервер временно недоступен. Попробуйте ещё раз.";
  return "Что-то пошло не так. Попробуйте ещё раз.";
}

const REFRESH_PATH = "/api/auth/refresh";
let refreshInFlight: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  refreshInFlight ??= fetch(REFRESH_PATH, { method: "POST", credentials: "same-origin" })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

type RequestOptions = Omit<RequestInit, "body"> & {
  json?: unknown;
  body?: BodyInit;
};

async function send(path: string, options: RequestOptions): Promise<Response> {
  const { json, headers, ...rest } = options;
  const init: RequestInit = { credentials: "same-origin", ...rest };
  if (json !== undefined) {
    init.body = JSON.stringify(json);
    init.headers = { "Content-Type": "application/json", ...headers };
  } else {
    init.headers = headers;
  }
  return fetch(path, init);
}

async function readDetail(response: Response): Promise<unknown> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return body.detail ?? body;
  } catch {
    return null;
  }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options);

  if (response.status === 401 && !path.startsWith("/api/auth/")) {
    if (await refreshSession()) {
      response = await send(path, options);
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readDetail(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function isApiError(error: unknown, status?: number): error is ApiError {
  return error instanceof ApiError && (status === undefined || error.status === status);
}
