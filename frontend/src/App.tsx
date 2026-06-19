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
const ServersPage = lazyPage(() => import("@/pages/servers"), "ServersPage");
const ServerDetailPage = lazyPage(() => import("@/pages/server-detail"), "ServerDetailPage");
const RulesPage = lazyPage(() => import("@/pages/rules"), "RulesPage");
const RuleGroupsPage = lazyPage(() => import("@/pages/rule-groups"), "RuleGroupsPage");
const AlertsPage = lazyPage(() => import("@/pages/alerts"), "AlertsPage");
const NotificationsPage = lazyPage(() => import("@/pages/notifications"), "NotificationsPage");
const MutesPage = lazyPage(() => import("@/pages/mutes"), "MutesPage");
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
        <Route path="/servers" element={<ServersPage />} />
        <Route path="/servers/:id" element={<ServerDetailPage />} />
        <Route path="/rules" element={<RulesPage />} />
        <Route path="/rule-groups" element={<RuleGroupsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/notifications" element={<NotificationsPage />} />
        <Route path="/mutes" element={<MutesPage />} />
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
