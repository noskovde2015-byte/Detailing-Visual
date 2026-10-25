import { useSyncExternalStore } from "react";

/**
 * Тема оформления.
 *
 * Пользователь выбирает «как в системе», «светлая» или «тёмная»; выбор
 * хранится в localStorage. На <html> всегда стоит уже вычисленная тема
 * (data-theme="light" | "dark") — CSS знает только о ней.
 *
 * Первую установку делает маленький скрипт в index.html ДО загрузки React,
 * иначе тёмная тема мигала бы белым при каждом открытии. Здесь — то же самое
 * плюс реакция на смену выбора и системной настройки.
 */
export type ThemePreference = "system" | "light" | "dark";
export type Theme = "light" | "dark";

const STORAGE_KEY = "theme";
const media = window.matchMedia("(prefers-color-scheme: dark)");
/** Цвет панели браузера на телефоне — совпадает с фоном страницы. */
const THEME_COLOR: Record<Theme, string> = { light: "#F5F5F7", dark: "#0B0C10" };

function readPreference(): ThemePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (value === "light" || value === "dark") return value;
  } catch {
    // Хранилище бывает недоступно (приватный режим, запрет cookies) — живём по системе.
  }
  return "system";
}

function resolve(preference: ThemePreference): Theme {
  if (preference === "system") return media.matches ? "dark" : "light";
  return preference;
}

let preference = readPreference();
let theme = resolve(preference);
const listeners = new Set<() => void>();

function apply() {
  theme = resolve(preference);
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
  for (const listener of listeners) listener();
}

// Пользователь сменил тему в системе — подхватываем, если выбрано «как в системе».
media.addEventListener("change", () => {
  if (preference === "system") apply();
});

// Тему сменили в другой вкладке — синхронизируем эту.
window.addEventListener("storage", (event) => {
  if (event.key !== STORAGE_KEY) return;
  preference = readPreference();
  apply();
});

export function setThemePreference(next: ThemePreference): void {
  preference = next;
  try {
    if (next === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Не сохранилось — тема всё равно сменится до перезагрузки.
  }
  apply();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Текущая тема и выбор пользователя; компонент перерисуется при смене. */
export function useTheme(): { theme: Theme; preference: ThemePreference } {
  const currentTheme = useSyncExternalStore(subscribe, () => theme);
  const currentPreference = useSyncExternalStore(subscribe, () => preference);
  return { theme: currentTheme, preference: currentPreference };
}

apply();
