import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { useMe } from "../api/queries";
import { formatRub, generationsCount } from "../lib/format";
import { PACKS, PAYMENTS_ENABLED, pricePerGeneration } from "../lib/pricing";
import { LockIcon } from "./icons";
import { Modal } from "./Modal";
import styles from "./PricingModal.module.css";

type PricingContextValue = { openPricing: (reason?: string) => void };

const PricingContext = createContext<PricingContextValue | null>(null);

/** Окно пополнения доступно отовсюду: из шапки, профиля и при ответе 402. */
export function PricingProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string | null>(null);

  const openPricing = useCallback((why?: string) => {
    setReason(why ?? null);
    setOpen(true);
  }, []);
  const value = useMemo(() => ({ openPricing }), [openPricing]);

  return (
    <PricingContext.Provider value={value}>
      {children}
      <PricingModal open={open} reason={reason} onClose={() => setOpen(false)} />
    </PricingContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function usePricing(): PricingContextValue {
  const value = useContext(PricingContext);
  if (!value) throw new Error("usePricing вне PricingProvider");
  return value;
}

function PricingModal({
  open,
  reason,
  onClose,
}: {
  open: boolean;
  reason: string | null;
  onClose: () => void;
}) {
  const { data: me } = useMe();

  return (
    <Modal open={open} onClose={onClose} labelledBy="pricing-title" size="lg">
      <div className={styles.head}>
        <h2 id="pricing-title" className={styles.title}>
          Пополнить баланс
        </h2>
        <p className={styles.lead}>
          {reason ??
            `Сейчас на балансе ${generationsCount(me?.balance ?? 0)}. Если генерация не получилась, она вернётся — платите только за результат.`}
        </p>
      </div>

      {!PAYMENTS_ENABLED && (
        <p className={`notice notice-info ${styles.soon}`} role="status">
          Онлайн-оплата подключается. Совсем скоро здесь можно будет купить пакет.
        </p>
      )}

      <ul className={styles.grid}>
        {PACKS.map((pack) => (
          <li key={pack.id} className={`${styles.pack} ${pack.highlight ? styles.highlight : ""}`}>
            <div className={styles.packTop}>
              <span className={styles.packName}>{pack.name}</span>
              {pack.badge && (
                <span className={`badge ${pack.highlight ? styles.badgeAccent : "badge-success"}`}>
                  {pack.badge}
                </span>
              )}
            </div>
            <div className={styles.count}>
              <span className={styles.countValue}>{pack.count}</span>
              <span className={styles.countLabel}>генераций</span>
            </div>
            <div>
              <div className={styles.price}>{formatRub(pack.price)}</div>
              <div className={styles.unit}>{formatRub(pricePerGeneration(pack))} за генерацию</div>
            </div>
            <button
              type="button"
              className={`btn ${pack.highlight ? "btn-primary" : "btn-secondary"} ${styles.buy}`}
              disabled={!PAYMENTS_ENABLED}
            >
              {PAYMENTS_ENABLED ? "Купить" : "Скоро"}
            </button>
          </li>
        ))}
      </ul>

      <p className={styles.footer}>
        <LockIcon size={14} />
        Оплата картой или через СБП · генерации не сгорают · без подписок и автосписаний
      </p>
    </Modal>
  );
}
