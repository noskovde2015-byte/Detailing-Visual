import { useEffect, useRef, type ReactNode } from "react";

import { CloseIcon } from "./icons";
import styles from "./Modal.module.css";

type ModalProps = {
  open: boolean;
  onClose: () => void;
  labelledBy: string;
  size?: "md" | "lg";
  children: ReactNode;
};

/**
 * Модальное окно на нативном <dialog>: браузер сам держит фокус внутри,
 * закрывает по Esc и делает остальную страницу недоступной для мыши и
 * экранных читалок.
 */
export function Modal({ open, onClose, labelledBy, size = "md", children }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className={`${styles.dialog} ${size === "lg" ? styles.large : ""}`}
      aria-labelledby={labelledBy}
      onClose={onClose}
      onClick={(event) => {
        // Клик по подложке (сам <dialog>, а не его содержимое) закрывает окно.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      {open && (
        <div className={styles.body}>
          <button type="button" className={styles.close} aria-label="Закрыть" onClick={onClose}>
            <CloseIcon />
          </button>
          {children}
        </div>
      )}
    </dialog>
  );
}
