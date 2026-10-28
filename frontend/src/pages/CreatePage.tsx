import { useRef, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { imageUrl, isActive, type FilmFinish, type GenerationParams } from "../api/api";
import { isApiError } from "../api/client";
import {
  useCreateGeneration,
  useGeneration,
  useGenerationAvailability,
} from "../api/queries";
import { FileDrop, Select, Switch } from "../components/controls";
import {
  CameraIcon,
  CarIcon,
  DownloadIcon,
  ImageIcon,
  ShieldCheckIcon,
  SunIcon,
  WheelIcon,
} from "../components/icons";
import { usePricing } from "../components/PricingModal";
import { FINISHES, SWATCHES, WHEEL_SIZES, swatchName } from "../lib/catalog";
import { generationsCount } from "../lib/format";
import { revealElement } from "../lib/smoothScroll";
import { useCurrentUser } from "../lib/useCurrentUser";
import styles from "./CreatePage.module.css";

type FilmMode = "photo" | "palette";
type View = "source" | "result";

const COMMENT_MAX = 500;
const DEFAULT_CUSTOM_COLOR = "#2E5E4E";

export function CreatePage() {
  const user = useCurrentUser();
  const { openPricing } = usePricing();
  const create = useCreateGeneration();
  // Генерации на паузе (у Google сбой для всех) — не даём отправить заведомо
  // не выполнимую задачу. Сервер всё равно проверит сам.
  const { data: availability } = useGenerationAvailability();
  const unavailable = availability?.available === false;

  const [car, setCar] = useState<File | null>(null);
  const [filmMode, setFilmMode] = useState<FilmMode>("photo");
  const [film, setFilm] = useState<File | null>(null);
  const [color, setColor] = useState<string | null>(null);
  const [customColor, setCustomColor] = useState(DEFAULT_CUSTOM_COLOR);
  const [finish, setFinish] = useState<FilmFinish | null>(null);
  const [antichrome, setAntichrome] = useState(false);
  const [tint, setTint] = useState(false);
  const [wheel, setWheel] = useState<File | null>(null);
  const [wheelCurrent, setWheelCurrent] = useState(18);
  const [wheelNew, setWheelNew] = useState(20);
  const [comment, setComment] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const previewRef = useRef<HTMLElement>(null);
  const commentRef = useRef<HTMLTextAreaElement>(null);

  // Переход к полю пожеланий из пояснения к антихрому.
  function focusComment() {
    const field = commentRef.current;
    if (!field) return;
    revealElement(field);
    field.focus({ preventScroll: true });
  }
  const [generationId, setGenerationId] = useState<string | null>(null);
  const [view, setView] = useState<View>("source");
  const { data: generation } = useGeneration(generationId);

  const running = generation ? isActive(generation) : false;
  const done = generation?.status === "done";
  const failed = generation?.status === "failed";
  const busy = create.isPending || running;

  // Плёнка задаётся либо фото, либо цветом — в зависимости от выбранной вкладки.
  const filmPhoto = filmMode === "photo" ? film : null;
  const filmColor = filmMode === "palette" ? color : null;
  const hasFilm = Boolean(filmPhoto || filmColor);

  const summary = buildSummary();

  function buildSummary(): string[] {
    const items: string[] = [];
    const finishLabel = FINISHES.find((f) => f.id === finish)?.adjective;
    if (filmColor) items.push([swatchName(filmColor), finishLabel].filter(Boolean).join(", "));
    if (filmPhoto) items.push(["Плёнка по фото", finishLabel].filter(Boolean).join(", "));
    if (antichrome) items.push("Антихром");
    if (tint) items.push("Тонировка");
    if (wheel) items.push(`Диски R${wheelCurrent} → R${wheelNew}`);
    if (comment.trim()) items.push("Пожелания");
    return items;
  }

  function buildParams(): GenerationParams {
    return {
      antichrome,
      tint,
      film_finish: hasFilm ? finish : null,
      film_color: filmColor,
      wheels: wheel ? { current_size: wheelCurrent, new_size: wheelNew } : null,
      comment: comment.trim() || null,
    };
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    if (!car) {
      setFormError("Загрузите фото автомобиля");
      return;
    }
    if (summary.length === 0) {
      setFormError("Выберите хотя бы одно изменение: плёнку, детали, диски или пожелание");
      return;
    }
    if (user.balance <= 0) {
      openPricing("На балансе закончились генерации. Пополните его, чтобы продолжить.");
      return;
    }

    try {
      const created = await create.mutateAsync({
        params: buildParams(),
        car,
        film: filmPhoto,
        wheel,
      });
      setGenerationId(created.id);
      setView("source");
      // На телефоне кнопка внизу длинной формы, а прогресс и результат — над ней,
      // за краем экрана. Показываем, что генерация пошла.
      if (previewRef.current) revealElement(previewRef.current, "start");
    } catch (error) {
      if (isApiError(error, 402)) {
        openPricing("На балансе закончились генерации. Пополните его, чтобы продолжить.");
      } else {
        setFormError(error instanceof Error ? error.message : "Не удалось создать генерацию");
      }
    }
  }

  // Когда результат готов, сразу показываем его.
  const [shownResultFor, setShownResultFor] = useState<string | null>(null);
  if (done && generation && shownResultFor !== generation.id) {
    setShownResultFor(generation.id);
    setView("result");
  }

  function startOver() {
    setGenerationId(null);
    setView("source");
  }

  return (
    <main className="page">
      <h1 className="sr-only">Новая визуализация</h1>
      <p className="page-lead">
        Загрузите фото автомобиля, выберите плёнку, детали и диски — мы покажем, как это будет
        выглядеть.
      </p>

      <form className={styles.layout} onSubmit={onSubmit} noValidate>
        {/* ---------------- превью ---------------- */}
        <section ref={previewRef} aria-labelledby="preview-title" className={styles.previewColumn}>
          <div className={styles.previewHead}>
            <h2 id="preview-title" className={styles.previewTitle}>
              Ваш автомобиль
            </h2>
            <div role="tablist" aria-label="Режим просмотра" className="segmented">
              <button
                type="button"
                role="tab"
                aria-selected={view === "source"}
                onClick={() => setView("source")}
              >
                Исходное
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={view === "result"}
                disabled={!done}
                onClick={() => setView("result")}
              >
                Результат
              </button>
            </div>
          </div>

          {view === "result" && done && generation ? (
            <div className={styles.stage}>
              <img
                src={imageUrl(generation.id, "result")}
                alt="Результат визуализации"
                className={styles.stageImage}
              />
            </div>
          ) : (
            <FileDrop
              file={car}
              onFile={(file) => {
                setCar(file);
                setFormError(null);
              }}
              onError={setFormError}
              label="Фото автомобиля"
              className={`${styles.stage} ${busy ? styles.stageLocked : ""}`}
            >
              {({ previewUrl }) =>
                previewUrl ? (
                  <>
                    <img src={previewUrl} alt="Фото вашего автомобиля" className={styles.stageImage} />
                    {!busy && <span className={styles.replace}>Заменить фото</span>}
                  </>
                ) : (
                  <span className={styles.placeholder}>
                    <span className={styles.placeholderIcon} aria-hidden="true">
                      <CarIcon size={30} />
                    </span>
                    {/* Перетаскивание есть только с мышью; на телефоне — камера или галерея. */}
                    <span className={`${styles.placeholderTitle} ${styles.forPointer}`}>
                      Перетащите фото автомобиля
                    </span>
                    <span className={`${styles.placeholderTitle} ${styles.forTouch}`}>
                      Добавьте фото автомобиля
                    </span>
                    <span className={styles.placeholderHint}>
                      <span className={styles.forPointer}>
                        или <u>выберите файл</u> · JPEG, PNG или WEBP до 15 МБ
                      </span>
                      <span className={styles.forTouch}>
                        <u>Сфотографируйте или выберите из галереи</u> · до 15 МБ
                      </span>
                    </span>
                  </span>
                )
              }
            </FileDrop>
          )}

          {running && (
            <div className={styles.progress} role="status">
              <span className="spinner" />
              <span>
                {generation?.status === "pending" ? "Генерация в очереди…" : "Генерируем…"} Обычно
                это занимает до минуты.
              </span>
            </div>
          )}
          {failed && generation && (
            <p className="notice notice-error" role="alert">
              {generation.error ?? "Не удалось выполнить генерацию."}
            </p>
          )}
          {done && generation && (
            <div className={styles.resultActions}>
              <a href={imageUrl(generation.id, "result", { download: true })} className="btn btn-dark">
                <DownloadIcon size={16} />
                Скачать
              </a>
              <Link to="/projects" className="btn btn-secondary">
                В мои проекты
              </Link>
              <button type="button" className="btn btn-ghost" onClick={startOver}>
                Новая визуализация
              </button>
            </div>
          )}

          <ul className={styles.tips}>
            <li>
              <CameraIcon className={styles.tipIcon} />
              Сбоку или в три четверти, машина целиком в кадре
            </li>
            <li>
              <SunIcon className={styles.tipIcon} />
              Дневной свет, без сильных бликов и теней
            </li>
            <li>
              <ShieldCheckIcon className={styles.tipIcon} />
              Фото видите только вы, номер можно не закрывать
            </li>
          </ul>
        </section>

        {/* ---------------- конфигуратор ---------------- */}
        <section aria-labelledby="config-title" className={`card ${styles.config}`}>
          <h2 id="config-title" className={styles.configTitle}>
            Конфигуратор
          </h2>

          <fieldset className={styles.group}>
            <legend className={styles.legend}>
              <span className={styles.step}>01</span>Кузов
            </legend>

            <div role="tablist" aria-label="Источник цвета плёнки" className={`segmented ${styles.fullTabs}`}>
              <button
                type="button"
                role="tab"
                aria-selected={filmMode === "photo"}
                onClick={() => setFilmMode("photo")}
              >
                Фото плёнки
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={filmMode === "palette"}
                onClick={() => setFilmMode("palette")}
              >
                Цвет из палитры
              </button>
            </div>

            {filmMode === "photo" ? (
              <FileDrop
                file={film}
                onFile={setFilm}
                onError={setFormError}
                label="Образец плёнки"
                className={styles.smallDrop}
              >
                {({ previewUrl }) => (
                  <span className={styles.smallDropInner}>
                    {previewUrl ? (
                      <img src={previewUrl} alt="" className={styles.thumb} />
                    ) : (
                      <span className={styles.thumbIcon} aria-hidden="true">
                        <ImageIcon size={24} />
                      </span>
                    )}
                    <span className={styles.smallDropText}>
                      <b>{film ? "Образец загружен" : "Загрузите образец плёнки"}</b>
                      <span>
                        {film ? "Нажмите, чтобы заменить" : "Крупный план, ровный свет — повторим цвет и фактуру"}
                      </span>
                    </span>
                    {film && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-icon"
                        aria-label="Убрать образец плёнки"
                        onClick={(event) => {
                          event.preventDefault();
                          setFilm(null);
                        }}
                      >
                        ✕
                      </button>
                    )}
                  </span>
                )}
              </FileDrop>
            ) : (
              <div className={styles.palette}>
                <div role="radiogroup" aria-label="Цвет плёнки" className={styles.swatches}>
                  {SWATCHES.map((swatch) => (
                    <button
                      key={swatch.id}
                      type="button"
                      role="radio"
                      aria-checked={color === swatch.hex}
                      aria-label={swatch.name}
                      title={swatch.name}
                      className={styles.swatch}
                      style={{ background: swatch.hex }}
                      onClick={() => setColor(color === swatch.hex ? null : swatch.hex)}
                    />
                  ))}
                </div>
                <label className={styles.custom}>
                  <input
                    type="color"
                    value={customColor}
                    aria-label="Свой цвет"
                    onChange={(event) => {
                      setCustomColor(event.target.value.toUpperCase());
                      setColor(event.target.value.toUpperCase());
                    }}
                  />
                  <span>Свой цвет</span>
                  <span className={styles.hex}>{customColor.toUpperCase()}</span>
                </label>
                {color && (
                  <div className={styles.current}>
                    <span className={styles.currentChip} style={{ background: color }} aria-hidden="true" />
                    <span>
                      <b>{swatchName(color)}</b>
                      <span>Цвет на экране приблизителен: он зависит от монитора и освещения</span>
                    </span>
                  </div>
                )}
              </div>
            )}

            <div className="field">
              <span id="finish-label" className="field-label">
                Покрытие {hasFilm ? "" : "· сначала выберите плёнку"}
              </span>
              <div role="radiogroup" aria-labelledby="finish-label" className={styles.finishes}>
                {FINISHES.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    role="radio"
                    aria-checked={finish === option.id}
                    disabled={!hasFilm}
                    className={styles.finish}
                    onClick={() => setFinish(finish === option.id ? null : option.id)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          </fieldset>

          <hr className={styles.divider} />

          <fieldset className={styles.group}>
            <legend className={styles.legend}>
              <span className={styles.step}>02</span>Детали
            </legend>
            <div>
              <Switch
                label="Антихром"
                hint="Весь хром на кузове станет чёрным глянцем"
                checked={antichrome}
                onChange={setAntichrome}
              />
              {antichrome && (
                <p className={styles.antichromeNote} role="note">
                  Сделаем полный антихром: молдинги и окантовка окон, решётка радиатора,
                  рейлинги, вставки в бамперах и эмблемы станут чёрным глянцем. Диски, фары и
                  номер не меняются. Хотите оставить что-то в хроме или поменять отделку —
                  напишите{" "}
                  <button type="button" className={styles.inlineLink} onClick={focusComment}>
                    в пожеланиях
                  </button>
                  , например: «эмблемы оставить хромированными».
                </p>
              )}
              <Switch
                label="Тонировка"
                hint="Боковые и заднее стекло, лобовое без изменений"
                checked={tint}
                onChange={setTint}
              />
            </div>
          </fieldset>

          <hr className={styles.divider} />

          <fieldset className={styles.group}>
            <legend className={styles.legend}>
              <span className={styles.step}>03</span>Диски
              <span className={styles.optional}>необязательно</span>
            </legend>
            <div className={styles.wheels}>
              <FileDrop
                file={wheel}
                onFile={setWheel}
                onError={setFormError}
                label="Фото дисков"
                className={styles.wheelDrop}
              >
                {({ previewUrl }) =>
                  previewUrl ? (
                    <>
                      <img src={previewUrl} alt="Фото дисков" className={styles.wheelImage} />
                      <button
                        type="button"
                        className={`btn btn-secondary btn-icon ${styles.removeWheel}`}
                        aria-label="Убрать фото дисков"
                        onClick={(event) => {
                          event.preventDefault();
                          setWheel(null);
                        }}
                      >
                        ✕
                      </button>
                    </>
                  ) : (
                    <>
                      <WheelIcon size={30} className={styles.accentIcon} />
                      <b>Фото дисков</b>
                      <span className={styles.muted}>Дизайн и цвет возьмём с фото</span>
                    </>
                  )
                }
              </FileDrop>
              <Select
                label="Сейчас на машине"
                value={wheelCurrent}
                options={WHEEL_SIZES}
                format={(size) => `R${size}`}
                onChange={setWheelCurrent}
              />
              <Select
                label="Новый диаметр"
                value={wheelNew}
                options={WHEEL_SIZES}
                format={(size) => `R${size}`}
                onChange={setWheelNew}
              />
            </div>
          </fieldset>

          <hr className={styles.divider} />

          <div className="field">
            <div className={styles.commentHead}>
              <label htmlFor="comment" className={styles.legend}>
                <span className={styles.step}>04</span>Пожелания
              </label>
              <span className={styles.counter}>
                {comment.length} / {COMMENT_MAX}
              </span>
            </div>
            <textarea
              ref={commentRef}
              id="comment"
              className={`input ${styles.comment}`}
              maxLength={COMMENT_MAX}
              rows={3}
              placeholder="Например: сделать суппорты красными"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
          </div>

          <div className={styles.summary}>
            <span className={styles.summaryTitle}>ИТОГ</span>
            {summary.length > 0 ? (
              <div className={styles.summaryChips}>
                {summary.map((item) => (
                  <span key={item} className={styles.summaryChip}>
                    {item}
                  </span>
                ))}
              </div>
            ) : (
              <span className={styles.muted}>Пока ничего не выбрано</span>
            )}

            {formError ? (
              <p className="notice notice-error" role="alert">
                {formError}
              </p>
            ) : (
              unavailable && (
                <p className={`notice ${styles.unavailable}`} role="status">
                  {availability.message ?? "Генерация временно недоступна, попробуйте позже."}
                </p>
              )
            )}

            <button type="submit" className="btn btn-primary btn-lg" disabled={busy || unavailable}>
              {create.isPending ? "Отправляем…" : running ? "Генерируем…" : "Создать визуализацию"}
            </button>
            <span className={styles.charge}>
              Спишется 1 генерация с баланса · сейчас {generationsCount(user.balance)} · если не
              получится, она вернётся
            </span>
          </div>
        </section>
      </form>
    </main>
  );
}
