import { useEffect, useId, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";

import { revealElement } from "../lib/smoothScroll";
import { ChevronIcon } from "./icons";
import styles from "./controls.module.css";

// ---------- переключатель ----------

export function Switch({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className={styles.switchRow}>
      <div className={styles.switchText}>
        <span id={`${id}-label`} className={styles.switchLabel}>
          {label}
        </span>
        {hint && <span className={styles.switchHint}>{hint}</span>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-label`}
        className={`${styles.switch} ${checked ? styles.switchOn : ""}`}
        onClick={() => onChange(!checked)}
      >
        <span className={styles.knob} aria-hidden="true" />
      </button>
    </div>
  );
}

// ---------- выпадающий список (диаметр дисков) ----------

export function Select<T extends string | number>({
  label,
  value,
  options,
  format,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  format: (value: T) => string;
  onChange: (value: T) => void;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // На телефоне список часто открывается у нижнего края — докручиваем, чтобы был виден.
  useEffect(() => {
    if (open && listRef.current) revealElement(listRef.current);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={styles.select} ref={rootRef}>
      <span id={`${id}-label`} className="field-label">
        {label}
      </span>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label ${id}-value`}
        className={`${styles.selectButton} ${open ? styles.selectOpen : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span id={`${id}-value`}>{format(value)}</span>
        <ChevronIcon className={styles.chevron} data-open={open} />
      </button>
      {open && (
        <div ref={listRef} role="listbox" aria-labelledby={`${id}-label`} className={styles.listbox}>
          {options.map((option) => (
            <button
              key={String(option)}
              type="button"
              role="option"
              aria-selected={option === value}
              className={`${styles.option} ${option === value ? styles.optionSelected : ""}`}
              onClick={() => {
                onChange(option);
                setOpen(false);
                buttonRef.current?.focus();
              }}
            >
              {format(option)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- загрузка файла ----------

const ACCEPTED_IMAGES = "image/jpeg,image/png,image/webp";
const MAX_FILE_BYTES = 15 * 1024 * 1024;

function validateImage(file: File): string | null {
  if (!ACCEPTED_IMAGES.split(",").includes(file.type)) {
    return "Поддерживаются только JPEG, PNG и WEBP";
  }
  if (file.size > MAX_FILE_BYTES) return "Файл больше 15 МБ";
  return null;
}

/**
 * Ссылка на локальный файл для превью.
 *
 * URL создаётся при рендере (useMemo), а освобождается отложенно: StrictMode
 * в dev сразу «перемонтирует» эффекты, и мгновенный revoke сломал бы превью.
 * Если тот же URL снова нужен — отложенный revoke отменяется.
 */
function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  const pending = useRef<{ url: string; timer: number } | null>(null);

  useEffect(() => {
    if (!url) return;
    if (pending.current?.url === url) {
      window.clearTimeout(pending.current.timer);
      pending.current = null;
    }
    return () => {
      pending.current = { url, timer: window.setTimeout(() => URL.revokeObjectURL(url), 0) };
    };
  }, [url]);

  return url;
}

export function FileDrop({
  file,
  onFile,
  onError,
  className,
  children,
  label,
}: {
  file: File | null;
  onFile: (file: File | null) => void;
  onError: (message: string) => void;
  className?: string;
  label: string;
  children: (state: { previewUrl: string | null; dragging: boolean }) => ReactNode;
}) {
  const [dragging, setDragging] = useState(false);
  const previewUrl = useObjectUrl(file);

  function accept(candidate: File | undefined) {
    if (!candidate) return;
    const error = validateImage(candidate);
    if (error) {
      onError(error);
      return;
    }
    onFile(candidate);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    accept(event.dataTransfer.files[0]);
  }

  return (
    <label
      className={`${styles.drop} ${dragging ? styles.dropActive : ""} ${file ? styles.dropFilled : ""} ${className ?? ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      {children({ previewUrl, dragging })}
      <input
        type="file"
        accept={ACCEPTED_IMAGES}
        aria-label={label}
        className="sr-only"
        onChange={(event) => {
          accept(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
    </label>
  );
}
