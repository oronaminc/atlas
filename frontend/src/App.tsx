import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/layout/app-layout";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { useAuth } from "@/hooks/use-auth";
import { LoginPage } from "@/pages/login";
import { lazyPage } from "@/lib/lazy-page";

// Route-level code-splitting: every authenticated page is its own async chunk,
// so the initial bundle stays small. /rules pulls Monaco — now only when opened.
const DashboardPage = lazyPage(() => import("@/pages/dashboard"), "DashboardPage");
const OpsPage = lazyPage(() => import("@/pages/ops"), "OpsPage");
const GraphPage = lazyPage(() => import("@/pages/graph")); // default export
const AlertsPage = lazyPage(() => import("@/pages/alerts"), "AlertsPage");
const IncidentsPage = lazyPage(() => import("@/pages/incidents"), "IncidentsPage");
const NotificationsPage = lazyPage(() => import("@/pages/notifications"), "NotificationsPage");
const ThresholdsPage = lazyPage(() => import("@/pages/thresholds"), "ThresholdsPage");
const GroupingRulesPage = lazyPage(() => import("@/pages/grouping-rules"), "GroupingRulesPage");
const NotificationDefaultsPage = lazyPage(
  () => import("@/pages/notification-defaults"),
  "NotificationDefaultsPage",
);
const GroupsPage = lazyPage(() => import("@/pages/groups"), "GroupsPage");
const UsersPage = lazyPage(() => import("@/pages/users"), "UsersPage");
const SettingsPage = lazyPage(() => import("@/pages/settings"), "SettingsPage");
const AuditPage = lazyPage(() => import("@/pages/audit"), "AuditPage");
const ProfilePage = lazyPage(() => import("@/pages/profile"), "ProfilePage");

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { hasRole } = useAuth();
  if (!hasRole("admin")) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/ops" element={<OpsPage />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/incidents" element={<IncidentsPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/thresholds" element={<ThresholdsPage />} />
        <Route
          path="/grouping-rules"
          element={
            <RequireAdmin>
              <GroupingRulesPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/notification-defaults"
          element={
            <RequireAdmin>
              <NotificationDefaultsPage />
            </RequireAdmin>
          }
        />
        <Route path="/groups" element={<GroupsPage />} />
        <Route
          path="/users"
          element={
            <RequireAdmin>
              <UsersPage />
            </RequireAdmin>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAdmin>
              <SettingsPage />
            </RequireAdmin>
          }
        />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/profile" element={<ProfilePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
