import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router";

import { imageUrl, type AdminUser, type CreditGrant, type Generation } from "../api/api";
import {
  ADMIN_PAGE_SIZE,
  useAdminCredits,
  useAdminStats,
  useAdminUser,
  useAdminUserGenerations,
  useAdminUsers,
  useGrantCredits,
  useSetBlocked,
} from "../api/queries";
import { CarIcon, SearchIcon } from "../components/icons";
import { formatDate, formatWhen, generationsCount } from "../lib/format";
import { revealElement } from "../lib/smoothScroll";
import { useCurrentUser } from "../lib/useCurrentUser";
import styles from "./AdminPage.module.css";

function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

export function AdminPage() {
  const me = useCurrentUser();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const debouncedSearch = useDebounced(search.trim(), 300);
  const panelRef = useRef<HTMLElement>(null);

  function selectUser(id: string) {
    setSelectedId(id);
    // На телефоне карточка стоит под таблицей, далеко внизу: без прокрутки
    // кажется, что нажатие ничего не сделало. На широком экране она рядом
    // с таблицей и уже на виду — там не двигаем страницу.
    requestAnimationFrame(() => {
      const panel = panelRef.current;
      const list = panel?.previousElementSibling;
      if (!panel || !list) return;
      const stacked = panel.getBoundingClientRect().top >= list.getBoundingClientRect().bottom;
      if (stacked) revealElement(panel, "start");
    });
  }

  if (!me.is_admin) return <Navigate to="/" replace />;

  return (
    <main className="page">
      <div className={styles.head}>
        <div>
          <h1 className={styles.title}>Панель администратора</h1>
          <p className={styles.lead}>Пункт «Админка» в меню видят только администраторы.</p>
        </div>
      </div>

      <Stats />

      <div className={styles.columns}>
        <section aria-labelledby="users-title" className={`card ${styles.users}`}>
          <div className={styles.usersHead}>
            <h2 id="users-title" className={styles.sectionTitle}>
              Пользователи
            </h2>
            <label className={styles.search}>
              <SearchIcon size={16} />
              <input
                type="search"
                value={search}
                placeholder="Поиск по почте или имени"
                aria-label="Поиск пользователей"
                maxLength={100}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setOffset(0);
                }}
              />
            </label>
          </div>
          <UsersTable
            search={debouncedSearch}
            offset={offset}
            onOffset={setOffset}
            selectedId={selectedId}
            onSelect={selectUser}
          />
        </section>

        <section
          ref={panelRef}
          aria-label="Карточка пользователя"
          className={`card ${styles.panel} ${selectedId ? styles.panelActive : ""}`}
        >
          {selectedId ? (
            <UserPanel key={selectedId} userId={selectedId} currentAdminId={me.id} />
          ) : (
            <p className={styles.placeholder}>Выберите пользователя в списке, чтобы увидеть детали</p>
          )}
        </section>
      </div>
    </main>
  );
}

// ---------- сводка ----------

function Stats() {
  const { data, isError } = useAdminStats();
  if (isError) return <p className="notice notice-error">Не удалось загрузить сводку</p>;

  const byStatus = data?.generations_24h_by_status ?? {};
  const done = byStatus.done ?? 0;
  const failed = byStatus.failed ?? 0;
  const active = (byStatus.pending ?? 0) + (byStatus.processing ?? 0);
  const total24 = data?.generations_24h ?? 0;
  const failRate = total24 ? ((failed / total24) * 100).toFixed(1).replace(".", ",") : "0";

  return (
    <section aria-label="Сводка за сутки" className={styles.stats}>
      <div className={`card ${styles.stat}`}>
        <span className={styles.statLabel}>Пользователи</span>
        <span className={styles.statValue}>{data?.users_total ?? "—"}</span>
        <span className={styles.statGood}>+{data?.users_new_24h ?? 0} новых за сутки</span>
      </div>
      <div className={`card ${styles.stat}`}>
        <span className={styles.statLabel}>Генерации за сутки</span>
        <span className={styles.statValue}>{data ? total24 : "—"}</span>
        <div className={styles.bar} aria-hidden="true">
          <span style={{ flex: done || 0.0001, background: "var(--accent-fill)" }} />
          <span style={{ flex: active, background: "#8e93c9" }} />
          <span style={{ flex: failed, background: "#d2453a" }} />
        </div>
        <span className={styles.statHint}>
          {done} готово · {active} в работе · {failed} ошибок
        </span>
      </div>
      <div className={`card ${styles.stat}`}>
        <span className={styles.statLabel}>Доля ошибок</span>
        <span className={styles.statValue}>{data ? `${failRate}%` : "—"}</span>
        <span className={styles.statHint}>Генерации вернулись на баланс</span>
      </div>
      <div className={`card ${styles.stat}`}>
        <span className={styles.statLabel}>Заблокированы</span>
        <span className={styles.statValue}>{data?.users_blocked ?? "—"}</span>
        <span className={styles.statHint}>Не могут войти и генерировать</span>
      </div>
    </section>
  );
}

// ---------- список ----------

function statusOf(user: AdminUser): { text: string; className: string } {
  if (user.is_blocked) return { text: "Заблокирован", className: "badge-danger" };
  if (user.is_admin) return { text: "Админ", className: "badge-accent" };
  return { text: "Активен", className: "badge-success" };
}

function UsersTable({
  search,
  offset,
  onOffset,
  selectedId,
  onSelect,
}: {
  search: string;
  offset: number;
  onOffset: (offset: number) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data, isPending, isError, error, isPlaceholderData } = useAdminUsers(search, offset);

  if (isPending) {
    return (
      <div className={styles.center}>
        <span className="spinner" role="status" aria-label="Загрузка" />
      </div>
    );
  }
  if (isError) return <p className="notice notice-error">{error.message}</p>;

  const shownTo = Math.min(offset + data.items.length, data.total);

  return (
    <>
      <div className={styles.tableScroll}>
        <table className={styles.table} aria-busy={isPlaceholderData}>
          <thead>
            <tr>
              <th scope="col">Пользователь</th>
              <th scope="col">Баланс</th>
              <th scope="col">Генераций</th>
              <th scope="col">Регистрация</th>
              <th scope="col">Статус</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((user) => {
              const status = statusOf(user);
              return (
                <tr key={user.id} className={user.id === selectedId ? styles.selected : undefined}>
                  <td>
                    <button
                      type="button"
                      className={styles.userButton}
                      aria-pressed={user.id === selectedId}
                      onClick={() => onSelect(user.id)}
                    >
                      <span className={styles.avatar} aria-hidden="true">
                        {(user.name || user.email).charAt(0).toUpperCase()}
                      </span>
                      <span className={styles.userText}>
                        <b>{user.name ?? "Без имени"}</b>
                        <span>{user.email}</span>
                        {/* На телефоне колонки «Статус» нет — особый статус пишем под почтой. */}
                        {(user.is_blocked || user.is_admin) && (
                          <span className={`badge ${status.className} ${styles.inlineStatus}`}>
                            {status.text}
                          </span>
                        )}
                      </span>
                    </button>
                  </td>
                  <td className={styles.num}>{user.balance}</td>
                  <td className={styles.num}>{user.generations_total}</td>
                  <td className={styles.date}>{formatDate(user.created_at)}</td>
                  <td>
                    <span className={`badge ${status.className}`}>{status.text}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {data.items.length === 0 && (
          <p className={styles.placeholder}>
            {search ? `Никого не нашли по запросу «${search}»` : "Пользователей пока нет"}
          </p>
        )}
      </div>
      <div className={styles.pager}>
        <span>
          {data.total ? `${offset + 1}–${shownTo} из ${data.total}` : "0 из 0"}
        </span>
        <div className={styles.pagerButtons}>
          <button
            type="button"
            className="btn btn-secondary btn-icon"
            aria-label="Предыдущая страница"
            disabled={offset === 0}
            onClick={() => onOffset(Math.max(offset - ADMIN_PAGE_SIZE, 0))}
          >
            ‹
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-icon"
            aria-label="Следующая страница"
            disabled={shownTo >= data.total}
            onClick={() => onOffset(offset + ADMIN_PAGE_SIZE)}
          >
            ›
          </button>
        </div>
      </div>
    </>
  );
}

// ---------- карточка пользователя ----------

function UserPanel({ userId, currentAdminId }: { userId: string; currentAdminId: string }) {
  const { data: user, isPending, isError, error } = useAdminUser(userId);

  if (isPending) {
    return (
      <div className={styles.center}>
        <span className="spinner" role="status" aria-label="Загрузка" />
      </div>
    );
  }
  if (isError) return <p className="notice notice-error">{error.message}</p>;

  return (
    <div className={styles.panelBody}>
      <div className={styles.panelHead}>
        <span className={`${styles.avatar} ${styles.avatarLarge}`} aria-hidden="true">
          {(user.name || user.email).charAt(0).toUpperCase()}
        </span>
        <div className={styles.panelWho}>
          <div className={styles.panelName}>
            <h2>{user.name ?? "Без имени"}</h2>
            {user.is_admin && <span className="badge badge-accent">Админ</span>}
            {user.is_blocked && <span className="badge badge-danger">Заблокирован</span>}
          </div>
          <span className={styles.panelEmail}>
            {user.email} · с {formatDate(user.created_at)}
          </span>
        </div>
      </div>

      <div className={styles.kpis}>
        <div>
          <span>Баланс</span>
          <b>{user.balance}</b>
        </div>
        <div>
          <span>Всего генераций</span>
          <b>{user.generations_total}</b>
        </div>
      </div>

      <BalanceForm user={user} />
      <CreditHistory userId={user.id} />
      <RecentGenerations userId={user.id} />
      <BlockControl user={user} isSelf={user.id === currentAdminId} />
    </div>
  );
}

function BalanceForm({ user }: { user: AdminUser }) {
  const grant = useGrantCredits(user.id);
  const [amount, setAmount] = useState("5");
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function submit(sign: 1 | -1) {
    const value = Number.parseInt(amount, 10);
    if (!Number.isFinite(value) || value < 1 || value > 1000) {
      setNotice({ kind: "error", text: "Укажите количество от 1 до 1000" });
      return;
    }
    if (sign < 0 && value > user.balance) {
      setNotice({ kind: "error", text: `Нельзя списать больше, чем на балансе (${user.balance})` });
      return;
    }
    try {
      await grant.mutateAsync({ amount: sign * value, reason: reason.trim() || null });
      setReason("");
      setNotice({
        kind: "ok",
        text: `${sign > 0 ? "Начислено" : "Списано"}: ${generationsCount(value)}`,
      });
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : "Ошибка" });
    }
  }

  return (
    <form
      className={styles.form}
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        void submit(1);
      }}
    >
      <h3 className={styles.subTitle}>Изменить баланс</h3>
      <div className={styles.formRow}>
        <label className="field">
          <span className="field-label">Сколько</span>
          <input
            className="input"
            type="number"
            inputMode="numeric"
            min={1}
            max={1000}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Причина (видна в истории)</span>
          <input
            className="input"
            type="text"
            maxLength={255}
            placeholder="Например: компенсация за ошибку"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </div>
      <div className={styles.formButtons}>
        <button type="submit" className="btn btn-primary" disabled={grant.isPending}>
          Начислить
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          disabled={grant.isPending}
          onClick={() => void submit(-1)}
        >
          Списать
        </button>
      </div>
      {notice && (
        <p role="status" className={`notice ${notice.kind === "ok" ? "notice-success" : "notice-error"}`}>
          {notice.text}
        </p>
      )}
    </form>
  );
}

const KIND_LABEL: Record<string, string> = {
  welcome: "подарок",
  admin: "администратор",
  purchase: "покупка",
};

function grantMeta(grant: CreditGrant): string {
  const who =
    grant.granted_by?.name ?? grant.granted_by?.email ?? KIND_LABEL[grant.kind] ?? grant.kind;
  return `${who} · ${formatWhen(grant.created_at)}`;
}

function CreditHistory({ userId }: { userId: string }) {
  const { data, isPending } = useAdminCredits(userId);
  return (
    <div className={styles.block}>
      <h3 className={styles.subTitle}>История баланса</h3>
      {isPending ? (
        <span className="spinner" />
      ) : !data || data.items.length === 0 ? (
        <p className={styles.muted}>Начислений пока не было</p>
      ) : (
        <ul className={styles.history}>
          {data.items.map((grant) => (
            <li key={grant.id}>
              <span className={`${styles.amount} ${grant.amount > 0 ? styles.plus : styles.minus}`}>
                {grant.amount > 0 ? "+" : "−"}
                {Math.abs(grant.amount)}
              </span>
              <span className={styles.historyText}>
                <span>{grant.reason ?? (grant.amount > 0 ? "Начисление" : "Списание")}</span>
                <span className={styles.muted}>{grantMeta(grant)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RecentGenerations({ userId }: { userId: string }) {
  const { data } = useAdminUserGenerations(userId);
  if (!data || data.items.length === 0) return null;

  return (
    <div className={styles.block}>
      <h3 className={styles.subTitle}>Последние генерации · {data.total}</h3>
      <div className={styles.recent}>
        {data.items.slice(0, 6).map((generation) => {
          const deleted = generation.deleted_at !== null;
          const status = deleted ? "удалена пользователем" : STATUS_TEXT[generation.status];
          const thumb = (
            <>
              <RecentThumb generation={generation} />
              <span
                className={`${styles.dot} ${styles[`dot_${generation.status}`] ?? ""}`}
                aria-hidden="true"
              />
            </>
          );
          // Файлы удалённых генераций уже стёрты — открывать нечего.
          return deleted ? (
            <div key={generation.id} className={`${styles.recentItem} ${styles.recentDeleted}`} title={status}>
              {thumb}
            </div>
          ) : (
            <a
              key={generation.id}
              href={imageUrl(generation.id, generation.status === "done" ? "result" : "car", {
                admin: true,
              })}
              target="_blank"
              rel="noreferrer"
              className={styles.recentItem}
              title={status}
            >
              {thumb}
            </a>
          );
        })}
      </div>
    </div>
  );
}

const STATUS_TEXT: Record<string, string> = {
  done: "готово",
  pending: "в очереди",
  processing: "генерируется",
  failed: "не удалось",
};

function RecentThumb({ generation }: { generation: Generation }) {
  const [broken, setBroken] = useState(false);
  const src =
    generation.status === "done" && generation.deleted_at === null
      ? imageUrl(generation.id, generation.preview_url ? "preview" : "result", { admin: true })
      : null;
  if (!src || broken) return <CarIcon size={28} />;
  return <img src={src} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

function BlockControl({ user, isSelf }: { user: AdminUser; isSelf: boolean }) {
  const setBlocked = useSetBlocked(user.id);
  const [confirming, setConfirming] = useState(false);
  const cannot = user.is_admin || isSelf;

  const hint = cannot
    ? "Администратора заблокировать нельзя"
    : user.is_blocked
      ? "Сможет снова войти и генерировать"
      : "Сразу выйдет из всех сессий и не сможет войти";

  async function apply() {
    await setBlocked.mutateAsync(!user.is_blocked);
    setConfirming(false);
  }

  return (
    <div className={styles.blockControl}>
      {confirming && !user.is_blocked ? (
        <div className={styles.confirm}>
          <span>Заблокировать {user.name ?? user.email}?</span>
          <div className={styles.formButtons}>
            <button type="button" className="btn btn-secondary" onClick={() => setConfirming(false)}>
              Отмена
            </button>
            <button type="button" className="btn btn-danger" disabled={setBlocked.isPending} onClick={apply}>
              Заблокировать
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className={`btn ${user.is_blocked ? "btn-secondary" : "btn-danger"}`}
          disabled={cannot || setBlocked.isPending}
          onClick={() => (user.is_blocked ? void apply() : setConfirming(true))}
        >
          {user.is_blocked ? "Разблокировать" : "Заблокировать пользователя"}
        </button>
      )}
      <span className={styles.muted}>{hint}</span>
      {setBlocked.isError && <p className="notice notice-error">{setBlocked.error.message}</p>}
    </div>
  );
}
