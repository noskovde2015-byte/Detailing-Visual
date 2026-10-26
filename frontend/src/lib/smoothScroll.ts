import Lenis from "lenis";
import "lenis/dist/lenis.css";

/**
 * Плавный инерционный скролл страницы (Lenis).
 *
 * Браузер сам колесо не сглаживает: страница прыгает рывками по 100px.
 * Lenis перехватывает wheel/touch и докручивает страницу с затуханием.
 *
 * Один экземпляр на всё приложение — поэтому модульная переменная,
 * а не контекст: модалкам и роутеру нужен только stop/start/scrollTo.
 */
let lenis: Lenis | null = null;
let locks = 0;

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Сенсорный экран без мыши (телефон, планшет). Палец и так прокручивает
 * плавно с инерцией — перехват жестов только ломал бы родное поведение
 * (резинку на краях, жест «назад», прокрутку внутри списков).
 */
function isTouchOnly(): boolean {
  return window.matchMedia("(hover: none) and (pointer: coarse)").matches;
}

/** Запускает плавный скролл. Возвращает функцию остановки (для cleanup эффекта). */
export function startSmoothScroll(): () => void {
  // Кого укачивает анимация, тем оставляем обычный скролл — это системная настройка.
  if (lenis || prefersReducedMotion() || isTouchOnly()) return () => undefined;

  const instance = new Lenis({
    autoRaf: true,
    lerp: 0.1,
    // Списки и таблицы со своей прокруткой крутятся сами, а не тащат страницу.
    allowNestedScroll: true,
    // Внутри модального окна скролл нативный: страница под ним заблокирована.
    prevent: (node) => node.nodeName === "DIALOG" || node.closest("dialog") !== null,
  });
  lenis = instance;
  if (locks > 0) instance.stop();

  return () => {
    instance.destroy();
    if (lenis === instance) lenis = null;
  };
}

/** Блокирует скролл страницы (пока открыта модалка). Возвращает разблокировку. */
export function lockScroll(): () => void {
  locks += 1;
  lenis?.stop();
  const previous = document.documentElement.style.overflow;
  // Без Lenis (reduced motion) блокируем вручную.
  if (!lenis) document.documentElement.style.overflow = "hidden";

  let released = false;
  return () => {
    if (released) return;
    released = true;
    locks -= 1;
    if (locks > 0) return;
    lenis?.start();
    if (!lenis) document.documentElement.style.overflow = previous;
  };
}

/** Мгновенно наверх — при переходе между страницами. */
export function scrollToTop(): void {
  if (lenis) lenis.scrollTo(0, { immediate: true, force: true });
  else window.scrollTo(0, 0);
}

/** Сколько сверху и снизу закрыто закреплёнными панелями (шапка, нижнее меню). */
function coveredEdges(): { top: number; bottom: number } {
  // Скрытый через display: none элемент даёт нулевой прямоугольник — то, что нужно.
  const header = document.querySelector("[data-app-header]")?.getBoundingClientRect();
  const tabbar = document.querySelector("[data-app-tabbar]")?.getBoundingClientRect();
  return {
    top: header ? Math.max(header.bottom, 0) : 0,
    bottom: tabbar ? tabbar.height : 0,
  };
}

/**
 * Докручивает страницу так, чтобы элемент оказался на виду, — только если он
 * сейчас (частично) скрыт: за краем экрана, под шапкой или нижним меню.
 *
 * align: "nearest" — сдвинуть ровно настолько, чтобы показать элемент
 * (раскрытый список); "start" — поставить начало элемента под шапку, если
 * оно не в верхней четверти видимой области (перейти к блоку целиком).
 */
export function revealElement(element: Element, align: "nearest" | "start" = "nearest"): void {
  const gap = 12;
  const { top: coveredTop, bottom: coveredBottom } = coveredEdges();
  const rect = element.getBoundingClientRect();
  const viewTop = coveredTop + gap;
  const viewBottom = window.innerHeight - coveredBottom - gap;

  let delta = 0;
  if (align === "start") {
    const comfortable = viewTop + (viewBottom - viewTop) * 0.25;
    if (rect.top < viewTop || rect.top > comfortable) delta = rect.top - viewTop;
  } else if (rect.bottom > viewBottom) {
    // Не уводим верх элемента под шапку, даже если он выше экрана.
    delta = Math.min(rect.bottom - viewBottom, rect.top - viewTop);
  } else if (rect.top < viewTop) {
    delta = rect.top - viewTop;
  }
  if (Math.abs(delta) < 1) return;

  const target = window.scrollY + delta;
  if (lenis) lenis.scrollTo(target);
  else window.scrollTo({ top: target, behavior: prefersReducedMotion() ? "auto" : "smooth" });
}
