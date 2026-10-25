import { useOutletContext } from "react-router";

import type { User } from "../api/api";

/** Текущий пользователь внутри AuthenticatedLayout (там он уже загружен). */
export function useCurrentUser(): User {
  return useOutletContext<User>();
}
