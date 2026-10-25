import { Link, useNavigate } from "react-router";

import { useGenerationTotal, useLogout } from "../api/queries";
import { GoogleIcon, MonitorIcon, MoonIcon, SparkIcon, SunIcon } from "../components/icons";
import { usePricing } from "../components/PricingModal";
import { formatDate, formatRub, GENERATION_FORMS, plural } from "../lib/format";
import { PACKS, pricePerGeneration } from "../lib/pricing";
import { setThemePreference, useTheme, type ThemePreference } from "../lib/theme";
import { useCurrentUser } from "../lib/useCurrentUser";
import styles from "./ProfilePage.module.css";

const cheapest = Math.min(...PACKS.map(pricePerGeneration));

export function ProfilePage() {
  const user = useCurrentUser();
  const { openPricing } = usePricing();
  const logout = useLogout();
  const navigate = useNavigate();
  const initial = (user.name || user.email).charAt(0).toUpperCase();

  const total = useGenerationTotal(null);
  const done = useGenerationTotal("done");
  const failed = useGenerationTotal("failed");

  async function onLogout() {
    await logout.mutateAsync().catch(() => undefined);
    navigate("/login", { replace: true });
  }

  return (
    <main className={`page ${styles.page}`}>
      <h1 className="sr-only">Профиль</h1>

      <section aria-label="Аккаунт" className={`card ${styles.account}`}>
        <div className={styles.avatarWrap}>
          <div className={styles.avatar} aria-hidden="true">
            {initial}
          </div>
          <span className={styles.google} title="Вход через Google">
            <GoogleIcon size={14} />
          </span>
        </div>
        <div className={styles.who}>
          <div className={styles.nameRow}>
            <span className={styles.name}>{user.name ?? "Без имени"}</span>
            {user.is_admin && <span className="badge badge-accent">Администратор</span>}
          </div>
          <span className={styles.email}>{user.email}</span>
          <span className={styles.since}>С нами с {formatDate(user.created_at)}</span>
        </div>
        <button type="button" className="btn btn-secondary" onClick={onLogout} disabled={logout.isPending}>
          Выйти
        </button>
      </section>

      <div className={styles.cards}>
        <section aria-labelledby="balance-title" className={`card ${styles.tile}`}>
          <h2 id="balance-title" className={styles.tileTitle}>
            Баланс генераций
          </h2>
          <div className={styles.big}>
            <span className={styles.bigValue}>{user.balance}</span>
            <span className={styles.bigLabel}>{plural(user.balance, GENERATION_FORMS)}</span>
          </div>
          <p className={styles.tileText}>
            Не сгорают. Одна генерация — одна визуализация. Если генерация не получилась, она
            вернётся на баланс.
          </p>
          <div className={styles.gift}>
            <SparkIcon className={styles.spark} />
            Первая генерация — подарок при регистрации
          </div>
        </section>

        <section aria-labelledby="packs-title" className={`${styles.tile} ${styles.dark}`}>
          <h2 id="packs-title" className={styles.tileTitle}>
            Пакеты генераций
          </h2>
          <div className={styles.big}>
            <span className={styles.bigLabel}>от</span>
            <span className={styles.bigValue}>{formatRub(cheapest)}</span>
            <span className={styles.bigLabel}>за генерацию</span>
          </div>
          <p className={styles.tileText}>
            Чем больше пакет, тем дешевле генерация. Без подписок и автосписаний.
          </p>
          <button type="button" className={`btn ${styles.light}`} onClick={() => openPricing()}>
            Выбрать пакет
          </button>
        </section>
      </div>

      <section aria-labelledby="stats-title" className={`card ${styles.stats}`}>
        <div className={styles.statsHead}>
          <h2 id="stats-title" className={styles.statsTitle}>
            Активность
          </h2>
          <Link to="/projects" className={styles.more}>
            Все проекты →
          </Link>
        </div>
        <div className={styles.statsGrid}>
          <Stat value={total.data} label="Всего визуализаций" />
          <Stat value={done.data} label="Готово" />
          <Stat value={failed.data} label="Не удалось · вернули на баланс" />
        </div>
      </section>

      <AppearanceSettings />
    </main>
  );
}

const THEME_OPTIONS: { value: ThemePreference; label: string; Icon: typeof SunIcon }[] = [
  { value: "system", label: "Системная", Icon: MonitorIcon },
  { value: "light", label: "Светлая", Icon: SunIcon },
  { value: "dark", label: "Тёмная", Icon: MoonIcon },
];

function AppearanceSettings() {
  const { preference } = useTheme();
  return (
    <section aria-labelledby="appearance-title" className={`card ${styles.appearance}`}>
      <div>
        <h2 id="appearance-title" className={styles.statsTitle}>
          Оформление
        </h2>
        <p className={styles.tileText}>
          «Системная» — тема меняется вместе с настройкой устройства. Выбор запоминается в этом
          браузере.
        </p>
      </div>
      <div role="radiogroup" aria-label="Тема оформления" className={`segmented ${styles.themes}`}>
        {THEME_OPTIONS.map(({ value, label, Icon }) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={preference === value}
            aria-pressed={preference === value}
            onClick={() => setThemePreference(value)}
          >
            <Icon size={16} />
            {label}
          </button>
        ))}
      </div>
    </section>
  );
}

function Stat({ value, label }: { value: number | undefined; label: string }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statValue}>{value ?? "—"}</span>
      <span className={styles.statLabel}>{label}</span>
    </div>
  );
}
