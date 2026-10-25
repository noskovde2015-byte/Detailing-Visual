import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <main className="page" style={{ textAlign: "center", paddingTop: 80 }}>
      <h1 className="page-title">Страница не найдена</h1>
      <p style={{ color: "var(--muted)", margin: "12px 0 24px" }}>
        Возможно, ссылка устарела или в ней опечатка.
      </p>
      <Link to="/" className="btn btn-primary">
        На главную
      </Link>
    </main>
  );
}
