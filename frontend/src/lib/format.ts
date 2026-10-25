const dateTime = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "long",
  hour: "2-digit",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric" });
const timeOnly = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** «Сегодня, 14:02», «Вчера, 21:47», «22 октября, 10:15». */
export function formatWhen(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameDay(date, now)) return `Сегодня, ${timeOnly.format(date)}`;
  if (sameDay(date, yesterday)) return `Вчера, ${timeOnly.format(date)}`;
  return dateTime.format(date);
}

export function formatDate(iso: string): string {
  return dateOnly.format(new Date(iso));
}

/** Склонение: plural(5, ["генерация", "генерации", "генераций"]) → «генераций». */
export function plural(count: number, forms: readonly [string, string, string]): string {
  const n = Math.abs(count) % 100;
  const last = n % 10;
  if (n > 10 && n < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}

export const GENERATION_FORMS = ["генерация", "генерации", "генераций"] as const;

export function generationsCount(count: number): string {
  return `${count} ${plural(count, GENERATION_FORMS)}`;
}

const rub = new Intl.NumberFormat("ru-RU");
export function formatRub(value: number): string {
  return `${rub.format(value)} ₽`;
}
