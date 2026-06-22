import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/layout/page-header";
import {
  NotificationSettingsCard,
  RecipientsCard,
} from "@/features/notifications/notification-admin";
import { LLMConfigCard } from "@/features/llm/llm-config-card";
import { RetentionCard } from "@/features/maintenance/retention-card";

export function SettingsPage() {
  const { t } = useTranslation();

  return (
    <div>
      <PageHeader title={t("settings.title")} description={t("settings.description")} />

      <div className="space-y-6">
        <RetentionCard />
        <LLMConfigCard />
        <NotificationSettingsCard />
        <RecipientsCard />
      </div>
    </div>
  );
}
