import { Link, NavLink } from "react-router";

import type { User } from "../api/api";
import logo from "../assets/logo.png";
import { generationsCount } from "../lib/format";
import styles from "./Header.module.css";
import { PlusIcon, ShieldIcon, SparkIcon } from "./icons";
import { usePricing } from "./PricingModal";

function navClass({ isActive }: { isActive: boolean }): string {
  return `${styles.navLink} ${isActive ? styles.active : ""}`;
}

export function Header({ user }: { user: User }) {
  const { openPricing } = usePricing();
  const initial = (user.name || user.email).charAt(0).toUpperCase();

  return (
    <header className={styles.wrap}>
      <div className={styles.bar}>
        <Link to="/" className={styles.logo} aria-label="Detailing.Visual — на главную">
          <img src={logo} alt="Detailing.Visual" width={153} height={30} />
        </Link>

        <nav aria-label="Основная навигация" className={styles.nav}>
          <NavLink to="/" end className={navClass}>
            Создание
          </NavLink>
          <NavLink to="/projects" className={navClass}>
            Мои проекты
          </NavLink>
          <NavLink to="/profile" className={navClass}>
            Профиль
          </NavLink>
          {user.is_admin && (
            <NavLink to="/admin" className={navClass}>
              <ShieldIcon size={14} />
              Админка
            </NavLink>
          )}
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
              Баланс <b>{generationsCount(user.balance)}</b>
            </span>
            <span className={styles.plus} aria-hidden="true">
              <PlusIcon size={12} />
            </span>
          </button>
          <Link to="/profile" className={styles.avatar} aria-label={`Профиль: ${user.name ?? user.email}`}>
            {initial}
          </Link>
        </div>
      </div>
    </header>
  );
}
