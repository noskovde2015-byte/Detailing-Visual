import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { isApiError } from "./api/client";
import { queryKeys } from "./api/queries";
import { App } from "./App";
import "./styles/global.css";

/**
 * Если пользователя заблокировали посреди сессии, любой запрос вернёт 403.
 * Перезапрашиваем /me — каркас увидит 403 и выведет на страницу входа.
 */
function onAnyError(error: unknown, queryKey?: readonly unknown[]) {
  // Сам /me не трогаем: иначе его 403 перезапускал бы его же по кругу.
  if (queryKey?.[0] === queryKeys.me[0]) return;
  if (isApiError(error, 403) && error.message === "Аккаунт заблокирован") {
    void queryClient.invalidateQueries({ queryKey: queryKeys.me });
  }
}

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (error, query) => onAnyError(error, query.queryKey) }),
  mutationCache: new MutationCache({ onError: (error) => onAnyError(error) }),
  defaultOptions: {
    queries: {
      // Ошибки 4xx повторять бессмысленно, сетевые сбои и 5xx — до двух раз.
      retry: (failureCount, error) =>
        failureCount < 2 && !(isApiError(error) && error.status < 500),
      refetchOnWindowFocus: true,
    },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("Нет элемента #root");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
