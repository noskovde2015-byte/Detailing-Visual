import type { FilmFinish, GenerationParams } from "../api/api";

export type Swatch = { id: string; name: string; hex: string };

/** Популярные цвета плёнки. HEX уходит на бэкенд как film_color. */
export const SWATCHES: readonly Swatch[] = [
  { id: "black", name: "Глубокий чёрный", hex: "#0B0B0C" },
  { id: "white", name: "Арктический белый", hex: "#F4F4F2" },
  { id: "nardo", name: "Нардо серый", hex: "#7A7D7F" },
  { id: "graphite", name: "Графит", hex: "#3A3D42" },
  { id: "silver", name: "Серебро", hex: "#B9BCC1" },
  { id: "midnight", name: "Полночный синий", hex: "#1B2440" },
  { id: "royal", name: "Королевский синий", hex: "#1F4FA3" },
  { id: "sky", name: "Небесный", hex: "#8EB8D8" },
  { id: "british", name: "Британский зелёный", hex: "#1F3D2B" },
  { id: "olive", name: "Оливковый", hex: "#5E6B45" },
  { id: "mint", name: "Мятный", hex: "#9FD3C1" },
  { id: "bordeaux", name: "Бордо", hex: "#5A1420" },
  { id: "red", name: "Гоночный красный", hex: "#C1121F" },
  { id: "orange", name: "Оранжевый", hex: "#E5641C" },
  { id: "yellow", name: "Жёлтый", hex: "#F2C230" },
  { id: "sand", name: "Песочный", hex: "#C8B79A" },
];

export const FINISHES: readonly { id: FilmFinish; label: string; adjective: string }[] = [
  { id: "glossy", label: "Глянец", adjective: "глянцевая" },
  { id: "matte", label: "Мат", adjective: "матовая" },
  { id: "satin", label: "Сатин", adjective: "сатиновая" },
  { id: "metallic", label: "Металлик", adjective: "металлик" },
];

export const WHEEL_SIZES: readonly number[] = Array.from({ length: 12 }, (_, i) => 13 + i);

export function swatchName(hex: string): string {
  const swatch = SWATCHES.find((s) => s.hex.toUpperCase() === hex.toUpperCase());
  return swatch ? swatch.name : `Свой цвет ${hex.toUpperCase()}`;
}

function finishAdjective(finish: FilmFinish | null | undefined): string | null {
  return FINISHES.find((f) => f.id === finish)?.adjective ?? null;
}

/** Короткое название генерации для карточки: «Графит, матовая». */
export function generationTitle(params: GenerationParams, inputRoles: string[]): string {
  const finish = finishAdjective(params.film_finish);
  if (params.film_color) {
    return [swatchName(params.film_color), finish].filter(Boolean).join(", ");
  }
  if (inputRoles.includes("film")) {
    return ["Плёнка по фото", finish].filter(Boolean).join(", ");
  }
  if (params.wheels) return "Новые диски";
  if (params.antichrome && params.tint) return "Антихром и тонировка";
  if (params.antichrome) return "Антихром";
  if (params.tint) return "Тонировка";
  return "Визуализация по пожеланиям";
}

/** Метки параметров для карточки и итога. */
export function generationChips(params: GenerationParams): string[] {
  const chips: string[] = [];
  if (params.antichrome) chips.push("Антихром");
  if (params.tint) chips.push("Тонировка");
  if (params.wheels) chips.push(`R${params.wheels.current_size} → R${params.wheels.new_size}`);
  if (params.comment?.trim()) chips.push("С пожеланиями");
  return chips;
}
