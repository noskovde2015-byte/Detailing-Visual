import { request } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type User = Schemas["UserRead"];
export type Generation = Schemas["GenerationRead"];
export type GenerationList = Schemas["GenerationList"];
export type GenerationParams = Schemas["GenerationParams"];
export type FilmFinish = Schemas["FilmFinish"];
export type AdminStats = Schemas["AdminStats"];
export type AdminUser = Schemas["AdminUserRead"];
export type AdminUserList = Schemas["AdminUserList"];
export type CreditGrant = Schemas["CreditGrantRead"];
export type CreditGrantList = Schemas["CreditGrantList"];

export type GenerationStatus = "pending" | "processing" | "done" | "failed";
export type ImageRole = "car" | "film" | "wheel" | "result" | "preview";

export const ACTIVE_STATUSES: readonly GenerationStatus[] = ["pending", "processing"];

export function isActive(generation: Pick<Generation, "status">): boolean {
  return ACTIVE_STATUSES.includes(generation.status as GenerationStatus);
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

// ---------- пользователь ----------

export const getMe = () => request<User>("/api/users/me");

export const logout = () => request<void>("/api/auth/logout", { method: "POST" });

export const GOOGLE_LOGIN_URL = "/api/auth/google/login";

// ---------- генерации ----------

export type CreateGenerationInput = {
  params: GenerationParams;
  car: File;
  film?: File | null;
  wheel?: File | null;
};

export function createGeneration(input: CreateGenerationInput): Promise<Generation> {
  const form = new FormData();
  form.set("params", JSON.stringify(input.params));
  form.set("car", input.car);
  if (input.film) form.set("film", input.film);
  if (input.wheel) form.set("wheel", input.wheel);
  return request<Generation>("/api/generations", { method: "POST", body: form });
}

export const getGeneration = (id: string) => request<Generation>(`/api/generations/${id}`);

export const listGenerations = (args: {
  limit: number;
  offset: number;
  status?: GenerationStatus | null;
}) => request<GenerationList>(`/api/generations${query(args)}`);

export const deleteGeneration = (id: string) =>
  request<void>(`/api/generations/${id}`, { method: "DELETE" });

export function imageUrl(
  generationId: string,
  role: ImageRole,
  options: { download?: boolean; admin?: boolean } = {},
): string {
  const base = options.admin ? "/api/admin/generations" : "/api/generations";
  return `${base}/${generationId}/images/${role}${options.download ? "?download=true" : ""}`;
}

// ---------- админка ----------

export const getAdminStats = () => request<AdminStats>("/api/admin/stats");

export const listAdminUsers = (args: { search?: string; limit: number; offset: number }) =>
  request<AdminUserList>(`/api/admin/users${query(args)}`);

export const getAdminUser = (id: string) => request<AdminUser>(`/api/admin/users/${id}`);

export const setUserBlocked = (id: string, isBlocked: boolean) =>
  request<AdminUser>(`/api/admin/users/${id}`, {
    method: "PATCH",
    json: { is_blocked: isBlocked },
  });

export const listUserCredits = (id: string, limit = 20) =>
  request<CreditGrantList>(`/api/admin/users/${id}/credits${query({ limit, offset: 0 })}`);

export const grantCredits = (id: string, amount: number, reason: string | null) =>
  request<CreditGrant>(`/api/admin/users/${id}/credits`, {
    method: "POST",
    json: { amount, reason },
  });

export const listUserGenerations = (id: string, limit = 6) =>
  request<GenerationList>(`/api/admin/users/${id}/generations${query({ limit, offset: 0 })}`);
