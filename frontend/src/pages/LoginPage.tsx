import { Navigate, useSearchParams } from "react-router";

import { GOOGLE_LOGIN_URL } from "../api/api";
import { useMe } from "../api/queries";
import logo from "../assets/logo.png";
import { GoogleIcon, SparkIcon } from "../components/icons";
import { FullPageSpinner } from "../components/Layout";
import styles from "./LoginPage.module.css";

/** Коды ошибок, с которыми бэкенд возвращает на /login?error=… */
const ERRORS: Record<string, string> = {
  oauth: "Не получилось войти через Google. Попробуйте ещё раз.",
  unavailable: "Google сейчас не отвечает. Попробуйте через минуту.",
  profile: "Google не передал почту. Проверьте доступы аккаунта и попробуйте снова.",
  email_not_verified: "Почта в Google-аккаунте не подтверждена.",
  account_conflict: "Эта почта уже привязана к другому Google-аккаунту.",
  blocked: "Аккаунт заблокирован. Напишите в поддержку, если это ошибка.",
};

export function LoginPage() {
  const { data: user, isPending } = useMe();
  const [params] = useSearchParams();
  const errorCode = params.get("error");
  const error = errorCode ? (ERRORS[errorCode] ?? ERRORS.oauth) : null;

  if (isPending) return <FullPageSpinner />;
  if (user) return <Navigate to="/" replace />;

  return (
    <main className={styles.page}>
      <div className={`card ${styles.card}`}>
        <img src={logo} alt="Detailing.Visual" className={styles.logo} width={204} height={40} />
        <h1 className={styles.title}>Ваша машина в новом цвете — до оклейки</h1>
        <p className={styles.lead}>
          Загрузите фото автомобиля, выберите плёнку, антихром, тонировку и диски — и посмотрите
          результат за минуту.
        </p>

        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}

        <a href={GOOGLE_LOGIN_URL} className={`btn btn-lg btn-secondary ${styles.google}`}>
          <GoogleIcon size={20} />
          Войти через Google
        </a>

        <p className={styles.gift}>
          <SparkIcon />
          Первая генерация — в подарок
        </p>
      </div>
    </main>
  );
}
