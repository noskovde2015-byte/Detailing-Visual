import { useState } from "react";
import { Link } from "react-router";

import { imageUrl, isActive, type Generation, type GenerationStatus } from "../api/api";
import { useDeleteGeneration, useGenerationList, useGenerationTotal } from "../api/queries";
import { CarIcon, DownloadIcon, PlusIcon, TrashIcon } from "../components/icons";
import { Modal } from "../components/Modal";
import { generationChips, generationTitle } from "../lib/catalog";
import { formatWhen } from "../lib/format";
import styles from "./ProjectsPage.module.css";

const PAGE_SIZE = 12;

const FILTERS: { status: GenerationStatus | null; label: string }[] = [
  { status: null, label: "Все" },
  { status: "done", label: "Готовые" },
  { status: "failed", label: "Неудачные" },
];

const STATUS_LABEL: Record<string, { text: string; className: string }> = {
  done: { text: "Готово", className: "badge-success" },
  pending: { text: "В очереди", className: "badge-accent" },
  processing: { text: "Генерируется", className: "badge-accent" },
  failed: { text: "Не удалось", className: "badge-danger" },
};

export function ProjectsPage() {
  const [status, setStatus] = useState<GenerationStatus | null>(null);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data, isPending, isError, error, isPlaceholderData } = useGenerationList(status, limit);
  const [viewing, setViewing] = useState<Generation | null>(null);
  const [deleting, setDeleting] = useState<Generation | null>(null);

  return (
    <main className="page">
      <div className={styles.head}>
        <div>
          <h1 className="page-title">Мои проекты</h1>
          <p className={styles.lead}>
            Все ваши визуализации хранятся здесь. Удалённые восстановить нельзя.
          </p>
        </div>
        <Link to="/" className="btn btn-primary">
          <PlusIcon size={16} />
          Новая визуализация
        </Link>
      </div>

      <div role="tablist" aria-label="Фильтр по статусу" className={styles.filters}>
        {FILTERS.map((filter) => (
          <FilterTab
            key={filter.label}
            label={filter.label}
            status={filter.status}
            selected={filter.status === status}
            onSelect={() => {
              setStatus(filter.status);
              setLimit(PAGE_SIZE);
            }}
          />
        ))}
      </div>

      {isPending ? (
        <div className={styles.center}>
          <span className="spinner spinner-lg" role="status" aria-label="Загрузка" />
        </div>
      ) : isError ? (
        <p className="notice notice-error" role="alert">
          {error.message}
        </p>
      ) : data.items.length === 0 ? (
        <div className={`card ${styles.empty}`}>
          <b>{status ? "Здесь пока пусто" : "Вы ещё ничего не создали"}</b>
          <span>
            {status ? "Визуализации с этим статусом появятся здесь" : "Первая визуализация займёт минуту"}
          </span>
          {!status && (
            <Link to="/" className="btn btn-primary">
              Создать визуализацию
            </Link>
          )}
        </div>
      ) : (
        <>
          <ul className={styles.grid} aria-busy={isPlaceholderData}>
            {data.items.map((generation) => (
              <ProjectCard
                key={generation.id}
                generation={generation}
                onOpen={() => setViewing(generation)}
                onDelete={() => setDeleting(generation)}
              />
            ))}
          </ul>
          {data.total > data.items.length && (
            <div className={styles.center}>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={isPlaceholderData}
                onClick={() => setLimit((value) => value + PAGE_SIZE)}
              >
                Показать ещё
              </button>
            </div>
          )}
        </>
      )}

      <ViewerModal key={viewing?.id ?? "none"} generation={viewing} onClose={() => setViewing(null)} />
      <DeleteModal generation={deleting} onClose={() => setDeleting(null)} />
    </main>
  );
}

function FilterTab({
  label,
  status,
  selected,
  onSelect,
}: {
  label: string;
  status: GenerationStatus | null;
  selected: boolean;
  onSelect: () => void;
}) {
  const { data: total } = useGenerationTotal(status);
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      className={styles.filter}
      onClick={onSelect}
    >
      {label}
      {total !== undefined && <span className={styles.count}>{total}</span>}
    </button>
  );
}

function Thumbnail({ generation }: { generation: Generation }) {
  const [broken, setBroken] = useState(false);
  const done = generation.status === "done";
  const src = done
    ? (generation.preview_url ?? generation.result_url)
    : generation.input_roles.includes("car")
      ? imageUrl(generation.id, "car")
      : null;

  if (!src || broken) {
    return (
      <div className={styles.thumbEmpty} aria-hidden="true">
        <CarIcon size={40} />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      className={`${styles.thumb} ${done ? "" : styles.thumbDim}`}
      onError={() => setBroken(true)}
    />
  );
}

function ProjectCard({
  generation,
  onOpen,
  onDelete,
}: {
  generation: Generation;
  onOpen: () => void;
  onDelete: () => void;
}) {
  const status = STATUS_LABEL[generation.status] ?? STATUS_LABEL.pending!;
  const running = isActive(generation);
  const title = generationTitle(generation.params, generation.input_roles);
  const chips = generationChips(generation.params);

  return (
    <li className={`card ${styles.card}`}>
      <div className={styles.media}>
        <Thumbnail generation={generation} />
        <span className={`badge ${status.className} ${styles.status}`}>{status.text}</span>
      </div>
      <div className={styles.body}>
        <div className={styles.titleRow}>
          <div className={styles.titleBlock}>
            <span className={styles.title}>{title}</span>
            <span className={styles.date}>{formatWhen(generation.created_at)}</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            aria-label={running ? "Удалить можно после завершения" : `Удалить: ${title}`}
            title={running ? "Удалить можно после завершения" : "Удалить"}
            disabled={running}
            onClick={onDelete}
          >
            <TrashIcon />
          </button>
        </div>
        {chips.length > 0 && (
          <div className={styles.chips}>
            {chips.map((chip) => (
              <span key={chip} className="chip">
                {chip}
              </span>
            ))}
          </div>
        )}
        {generation.status === "failed" && (
          <p className={styles.error}>
            {generation.error ?? "Не удалось выполнить генерацию."}
          </p>
        )}
        {running && (
          <div className={styles.pending}>
            <span className="spinner" />
            Обычно занимает до минуты
          </div>
        )}
        {generation.status === "done" && (
          <div className={styles.actions}>
            <button type="button" className="btn btn-dark" onClick={onOpen}>
              Открыть
            </button>
            <a href={imageUrl(generation.id, "result", { download: true })} className="btn btn-secondary">
              <DownloadIcon size={16} />
              Скачать
            </a>
          </div>
        )}
      </div>
    </li>
  );
}

function ViewerModal({ generation, onClose }: { generation: Generation | null; onClose: () => void }) {
  const [view, setView] = useState<"result" | "car">("result");
  const title = generation ? generationTitle(generation.params, generation.input_roles) : "";

  return (
    <Modal open={generation !== null} onClose={onClose} labelledBy="viewer-title" size="lg">
      {generation && (
        <div className={styles.viewer}>
          <div className={styles.viewerHead}>
            <div>
              <h2 id="viewer-title" className={styles.viewerTitle}>
                {title}
              </h2>
              <span className={styles.date}>{formatWhen(generation.created_at)}</span>
            </div>
            <div role="tablist" aria-label="Режим просмотра" className="segmented">
              <button type="button" role="tab" aria-selected={view === "car"} onClick={() => setView("car")}>
                Исходное
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "result"}
                onClick={() => setView("result")}
              >
                Результат
              </button>
            </div>
          </div>
          <img
            src={imageUrl(generation.id, view)}
            alt={view === "result" ? "Результат визуализации" : "Исходное фото"}
            className={styles.viewerImage}
          />
          <div className={styles.viewerActions}>
            <a href={imageUrl(generation.id, "result", { download: true })} className="btn btn-primary">
              <DownloadIcon size={16} />
              Скачать результат
            </a>
            <span className={styles.disclaimer}>
              Визуализация приблизительная: реальный цвет плёнки может отличаться.
            </span>
          </div>
        </div>
      )}
    </Modal>
  );
}

function DeleteModal({ generation, onClose }: { generation: Generation | null; onClose: () => void }) {
  const remove = useDeleteGeneration();

  async function confirm() {
    if (!generation) return;
    await remove.mutateAsync(generation.id);
    onClose();
  }

  return (
    <Modal
      open={generation !== null}
      onClose={() => {
        remove.reset();
        onClose();
      }}
      labelledBy="delete-title"
    >
      <div className={styles.confirm}>
        <h2 id="delete-title" className={styles.viewerTitle}>
          Удалить визуализацию?
        </h2>
        <p>Фото и результат будут удалены без возможности восстановления. Генерация на баланс не вернётся.</p>
        {remove.isError && (
          <p className="notice notice-error" role="alert">
            {remove.error.message}
          </p>
        )}
        <div className={styles.confirmActions}>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            Отмена
          </button>
          <button type="button" className="btn btn-danger" disabled={remove.isPending} onClick={confirm}>
            {remove.isPending ? "Удаляем…" : "Удалить"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
