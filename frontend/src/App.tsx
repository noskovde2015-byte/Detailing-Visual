import { useEffect } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import { AuthenticatedLayout } from "./components/Layout";
import { startSmoothScroll } from "./lib/smoothScroll";
import { AdminPage } from "./pages/AdminPage";
import { CreatePage } from "./pages/CreatePage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ProjectsPage } from "./pages/ProjectsPage";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: <AuthenticatedLayout />,
    children: [
      { index: true, element: <CreatePage /> },
      { path: "projects", element: <ProjectsPage /> },
      { path: "profile", element: <ProfilePage /> },
      { path: "admin", element: <AdminPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);

export function App() {
  useEffect(() => startSmoothScroll(), []);
  return <RouterProvider router={router} />;
}
