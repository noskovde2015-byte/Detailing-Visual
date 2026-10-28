import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import * as api from "./api";
import { isApiError } from "./client";

export const queryKeys = {
  me: ["me"] as const,
  generation: (id: string) => ["generation", id] as const,
  generations: ["generations"] as const,
  generationAvailability: ["generation-availability"] as const,
  generationList: (status: api.GenerationStatus | null, limit: number) =>
    ["generations", "list", status, limit] as const,
  generationTotal: (status: api.GenerationStatus | null) =>
    ["generations", "total", status] as const,
  admin: ["admin"] as const,
  adminStats: ["admin", "stats"] as const,
  adminGenerationControl: ["admin", "generation-control"] as const,
  adminUsers: (search: string, offset: number) => ["admin", "users", search, offset] as const,
  adminUser: (id: string) => ["admin", "user", id] as const,
  adminCredits: (id: string) => ["admin", "credits", id] as const,
  adminUserGenerations: (id: string) => ["admin", "user-generations", id] as const,
};

/** Как часто опрашивать генерацию, пока она в очереди или выполняется. */
const POLL_INTERVAL_MS = 2000;
/** Как часто проверять, не встали ли генерации (и не пошли ли снова). */
const AVAILABILITY_INTERVAL_MS = 60_000;

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: async () => {
      try {
        return await api.getMe();
      } catch (error) {
        // 401 после попытки обновить сессию — просто «не вошёл», а не ошибка.
        if (isApiError(error, 401)) return null;
        throw error;
      }
    },
    staleTime: 30_000,
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      client.clear();
      client.setQueryData(queryKeys.me, null);
    },
  });
}

export function useGeneration(id: string | null) {
  return useQuery({
    queryKey: queryKeys.generation(id ?? ""),
    queryFn: () => api.getGeneration(id as string),
    enabled: id !== null,
    refetchInterval: (query) =>
      query.state.data && api.isActive(query.state.data) ? POLL_INTERVAL_MS : false,
  });
}

export function useCreateGeneration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.createGeneration,
    onSuccess: (generation) => {
      client.setQueryData(queryKeys.generation(generation.id), generation);
    },
    onError: (error) => {
      // 503 — генерации на паузе: обновить плашку, а не ждать минуту.
      if (isApiError(error, 503)) {
        void client.invalidateQueries({ queryKey: queryKeys.generationAvailability });
      }
    },
    onSettled: () => {
      // Баланс уменьшился (или вернулся при ошибке), список проектов изменился.
      void client.invalidateQueries({ queryKey: queryKeys.me });
      void client.invalidateQueries({ queryKey: queryKeys.generations });
    },
  });
}

export function useGenerationAvailability() {
  return useQuery({
    queryKey: queryKeys.generationAvailability,
    queryFn: api.getGenerationAvailability,
    refetchInterval: AVAILABILITY_INTERVAL_MS,
    staleTime: 15_000,
  });
}

export function useGenerationList(status: api.GenerationStatus | null, limit: number) {
  return useQuery({
    queryKey: queryKeys.generationList(status, limit),
    queryFn: () => api.listGenerations({ status, limit, offset: 0 }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some(api.isActive) ? POLL_INTERVAL_MS * 2 : false,
  });
}

export function useGenerationTotal(status: api.GenerationStatus | null) {
  return useQuery({
    queryKey: queryKeys.generationTotal(status),
    queryFn: async () => (await api.listGenerations({ status, limit: 1, offset: 0 })).total,
  });
}

export function useDeleteGeneration() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.deleteGeneration,
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.generations }),
  });
}

// ---------- админка ----------

export function useAdminStats() {
  return useQuery({ queryKey: queryKeys.adminStats, queryFn: api.getAdminStats });
}

export const ADMIN_PAGE_SIZE = 20;

export function useAdminUsers(search: string, offset: number) {
  return useQuery({
    queryKey: queryKeys.adminUsers(search, offset),
    queryFn: () => api.listAdminUsers({ search, limit: ADMIN_PAGE_SIZE, offset }),
    placeholderData: keepPreviousData,
  });
}

export function useAdminUser(id: string | null) {
  return useQuery({
    queryKey: queryKeys.adminUser(id ?? ""),
    queryFn: () => api.getAdminUser(id as string),
    enabled: id !== null,
  });
}

export function useAdminCredits(id: string | null) {
  return useQuery({
    queryKey: queryKeys.adminCredits(id ?? ""),
    queryFn: () => api.listUserCredits(id as string),
    enabled: id !== null,
  });
}

export function useAdminUserGenerations(id: string | null) {
  return useQuery({
    queryKey: queryKeys.adminUserGenerations(id ?? ""),
    queryFn: () => api.listUserGenerations(id as string),
    enabled: id !== null,
  });
}

export function useGrantCredits(userId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: { amount: number; reason: string | null }) =>
      api.grantCredits(userId, input.amount, input.reason),
    onSuccess: async () => {
      // Админ может начислить и себе — тогда меняется баланс в шапке.
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.admin }),
        client.invalidateQueries({ queryKey: queryKeys.me }),
      ]);
    },
  });
}

export function useSetBlocked(userId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (isBlocked: boolean) => api.setUserBlocked(userId, isBlocked),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.admin }),
  });
}

/**
 * Идут ли генерации. intervalMs — как часто опрашивать: в админке чаще,
 * в шапке (точка на «Админке») — раз в минуту.
 */
export function useGenerationControl(options: { enabled?: boolean; intervalMs: number }) {
  return useQuery({
    queryKey: queryKeys.adminGenerationControl,
    queryFn: api.getGenerationControl,
    enabled: options.enabled ?? true,
    refetchInterval: options.intervalMs,
  });
}

function useGenerationControlMutation<T, A>(mutationFn: (arg: A) => Promise<T>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn,
    onSettled: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: queryKeys.admin }),
        client.invalidateQueries({ queryKey: queryKeys.generationAvailability }),
      ]);
    },
  });
}

export function usePauseGenerations() {
  return useGenerationControlMutation((comment: string | null) => api.pauseGenerations(comment));
}

export function useResumeGenerations() {
  return useGenerationControlMutation(() => api.resumeGenerations());
}
