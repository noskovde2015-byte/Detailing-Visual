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

/** Запускает плавный скролл. Возвращает функцию остановки (для cleanup эффекта). */
export function startSmoothScroll(): () => void {
  // Кого укачивает анимация, тем оставляем обычный скролл — это системная настройка.
  if (lenis || prefersReducedMotion()) return () => undefined;

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
