import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Shell } from "./components/Shell";
import { Button, ErrorNote, Loading } from "./components/ui";
import { ActionsPage } from "./pages/ActionsPage";
import { AgentsPage } from "./pages/AgentsPage";
import { LoginPage, SignupPage } from "./pages/AuthPages";
import { ConnectionsPage } from "./pages/ConnectionsPage";
import { GraphPage } from "./pages/GraphPage";
import { OperatorsPage } from "./pages/OperatorsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";
import { SchedulesPage } from "./pages/SchedulesPage";
import { SettingsPage } from "./pages/SettingsPage";

function RequireAuth() {
  const { status, startupError, retry, logout } = useAuth();
  const location = useLocation();

  if (status === "signed-out") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (status === "loading") {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        {startupError ? (
          <div className="space-y-4">
            <ErrorNote message={startupError} onRetry={retry} />
            <Button onClick={logout}>Sign out</Button>
          </div>
        ) : (
          <Loading label="Loading your workspace" />
        )}
      </div>
    );
  }
  return <Outlet />;
}

function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-muted">That address does not match anything here.</p>
    </div>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<Shell />}>
          <Route index element={<OverviewPage />} />
          <Route path="connections" element={<ConnectionsPage />} />
          <Route path="actions" element={<ActionsPage />} />
          <Route path="operators" element={<OperatorsPage />} />
          <Route path="schedules" element={<SchedulesPage />} />
          <Route path="runs" element={<RunsPage />} />
          <Route path="runs/:runId" element={<RunDetailPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
