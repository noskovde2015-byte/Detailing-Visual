import { useEffect, useState } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import { logout } from "../api/api";
import { isApiError } from "../api/client";
import { useMe } from "../api/queries";
import { Header } from "./Header";
import { PricingProvider } from "./PricingModal";

export function FullPageSpinner() {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}>
      <span className="spinner spinner-lg" role="status" aria-label="Загрузка" />
    </div>
  );
}

export function FullPageError({ message }: { message: string }) {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: 16 }}>
      <div className="card" style={{ padding: 32, maxWidth: 420, textAlign: "center" }}>
        <p style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>Не удалось загрузить</p>
        <p style={{ color: "var(--muted)", marginBottom: 20 }}>{message}</p>
        <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
          Обновить страницу
        </button>
      </div>
    </div>
  );
}

/** Каркас страниц для вошедшего пользователя. Без входа — на /login. */
export function AuthenticatedLayout() {
  const { data: user, isPending, isError, error } = useMe();
  const location = useLocation();

  if (isPending) return <FullPageSpinner />;
  if (isError) {
    // 403 на /me бывает только у заблокированного: сессию гасим и объясняем на странице входа.
    if (isApiError(error, 403)) return <SignOutBlocked />;
    return <FullPageError message={error.message} />;
  }
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return (
    <PricingProvider>
      <Header user={user} />
      <Outlet context={user} />
    </PricingProvider>
  );
}

function SignOutBlocked() {
  const [done, setDone] = useState(false);
  useEffect(() => {
    let alive = true;
    // Ошибка выхода не важна: без refresh-токена сессия всё равно не продлится.
    void logout()
      .catch(() => undefined)
      .finally(() => alive && setDone(true));
    return () => {
      alive = false;
    };
  }, []);
  return done ? <Navigate to="/login?error=blocked" replace /> : <FullPageSpinner />;
}
