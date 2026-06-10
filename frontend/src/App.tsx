import { Navigate, Route, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { AppLayout } from "@/components/layout/app-layout";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { useAuth } from "@/hooks/use-auth";
import { LoginPage } from "@/pages/login";
import { PlaceholderPage } from "@/pages/placeholder";

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

export default function App() {
  const { t } = useTranslation();

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
        <Route path="/" element={<PlaceholderPage title={t("nav.dashboard")} />} />
        <Route path="/servers" element={<PlaceholderPage title={t("nav.servers")} />} />
        <Route path="/servers/:id" element={<PlaceholderPage title={t("nav.servers")} />} />
        <Route path="/rules" element={<PlaceholderPage title={t("nav.rules")} />} />
        <Route path="/rule-groups" element={<PlaceholderPage title={t("nav.ruleGroups")} />} />
        <Route path="/alerts" element={<PlaceholderPage title={t("nav.alerts")} />} />
        <Route path="/notifications" element={<PlaceholderPage title={t("nav.notifications")} />} />
        <Route path="/groups" element={<PlaceholderPage title={t("nav.groups")} />} />
        <Route path="/users" element={<PlaceholderPage title={t("nav.users")} />} />
        <Route path="/audit" element={<PlaceholderPage title={t("nav.audit")} />} />
        <Route path="/profile" element={<PlaceholderPage title={t("nav.profile")} />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
