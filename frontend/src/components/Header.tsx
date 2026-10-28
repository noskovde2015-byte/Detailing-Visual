import { Link, NavLink } from "react-router";

import type { User } from "../api/api";
import { useGenerationControl } from "../api/queries";
import logo from "../assets/logo.png";
import { GENERATION_FORMS, generationsCount, plural } from "../lib/format";
import { setThemePreference, useTheme } from "../lib/theme";
import styles from "./Header.module.css";
import {
  GridIcon,
  MoonIcon,
  PlusIcon,
  ShieldIcon,
  SparkIcon,
  SunIcon,
  UserIcon,
  WandIcon,
} from "./icons";
import { usePricing } from "./PricingModal";

type NavItem = { to: string; label: string; short: string; Icon: typeof GridIcon; end?: boolean };

function navItems(user: User): NavItem[] {
  const items: NavItem[] = [
    { to: "/", label: "Создание", short: "Создание", Icon: WandIcon, end: true },
    { to: "/projects", label: "Мои проекты", short: "Проекты", Icon: GridIcon },
    { to: "/profile", label: "Профиль", short: "Профиль", Icon: UserIcon },
  ];
  if (user.is_admin) items.push({ to: "/admin", label: "Админка", short: "Админка", Icon: ShieldIcon });
  return items;
}

/**
 * Шапка. На широком экране — одна плавающая панель с навигацией по центру.
 * На телефоне навигация уезжает в нижнее меню (как в приложениях): до него
 * дотягивается большой палец, а сверху остаётся одна компактная строка.
 * Обе навигации в разметке, лишняя скрыта через display: none — так её не
 * видят и экранные читалки.
 */
export function Header({ user }: { user: User }) {
  const { openPricing } = usePricing();
  const initial = (user.name || user.email).charAt(0).toUpperCase();
  const { theme } = useTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";
  const items = navItems(user);
  // Админ должен узнать о паузе генераций, где бы он ни был на сайте.
  const control = useGenerationControl({ enabled: user.is_admin, intervalMs: 60_000 });
  const alertOn = (to: string) => to === "/admin" && control.data?.paused === true;
  const alertDot = (
    <span className={styles.alertDot} title="Генерации на паузе">
      <span className="sr-only">: генерации на паузе</span>
    </span>
  );

  return (
    <>
      <header className={styles.wrap} data-app-header>
        <div className={styles.bar}>
          <Link to="/" className={styles.logo} aria-label="Detailing.Visual — на главную">
            <img src={logo} alt="Detailing.Visual" width={153} height={30} className="logo-img" />
          </Link>

          <nav aria-label="Основная навигация" className={styles.nav}>
            {items.map(({ to, label, Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) => `${styles.navLink} ${isActive ? styles.active : ""}`}
              >
                {to === "/admin" && <Icon size={14} />}
                {label}
                {alertOn(to) && alertDot}
              </NavLink>
            ))}
          </nav>

          <div className={styles.right}>
            <button
              type="button"
              className={styles.balance}
              onClick={() => openPricing()}
              aria-label={`Баланс: ${generationsCount(user.balance)}. Пополнить`}
            >
              <SparkIcon className={styles.spark} />
              <span>
                <span className={styles.balanceWord}>Баланс </span>
                <b>
                  {user.balance}
                  <span className={styles.balanceWord}> {plural(user.balance, GENERATION_FORMS)}</span>
                </b>
              </span>
              <span className={styles.plus} aria-hidden="true">
                <PlusIcon size={12} />
              </span>
            </button>
            {/* Быстрое переключение; «Системная» — в профиле. */}
            <button
              type="button"
              className={styles.themeToggle}
              onClick={() => setThemePreference(nextTheme)}
              aria-label={nextTheme === "dark" ? "Включить тёмную тему" : "Включить светлую тему"}
              title={nextTheme === "dark" ? "Тёмная тема" : "Светлая тема"}
            >
              {theme === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
            </button>
            <Link to="/profile" className={styles.avatar} aria-label={`Профиль: ${user.name ?? user.email}`}>
              {initial}
            </Link>
          </div>
        </div>
      </header>

      <nav aria-label="Основная навигация" className={styles.tabbar} data-app-tabbar>
        {items.map(({ to, short, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `${styles.tab} ${isActive ? styles.tabActive : ""}`}
          >
            <span className={styles.tabIcon}>
              <Icon size={22} />
              {alertOn(to) && alertDot}
            </span>
            {short}
          </NavLink>
        ))}
      </nav>
    </>
  );
}
