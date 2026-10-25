export type Pack = {
  id: string;
  name: string;
  count: number;
  price: number;
  badge?: string;
  highlight?: boolean;
};

/**
 * Пакеты для частных клиентов. Одинаковый объём — одинаковая цена для всех;
 * студиям — отдельные тарифы с подпиской. Цены пока черновые.
 */
export const PACKS: readonly Pack[] = [
  { id: "start", name: "Старт", count: 10, price: 590 },
  { id: "choice", name: "Выбор", count: 30, price: 1490, badge: "Выгода 16%" },
  { id: "optimal", name: "Максимум", count: 60, price: 2690, badge: "Популярный", highlight: true },
  { id: "studio", name: "Студийный", count: 150, price: 5990, badge: "Выгода 32%" },
];

export function pricePerGeneration(pack: Pack): number {
  return Math.round(pack.price / pack.count);
}

/** Онлайн-оплата ещё не подключена: кнопки покупки неактивны. */
export const PAYMENTS_ENABLED = false;
