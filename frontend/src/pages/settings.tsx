import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/layout/page-header";
import { SamlConfigCard } from "@/features/auth/saml-config-card";
import { LLMConfigCard } from "@/features/llm/llm-config-card";
import { MimirQueryCard } from "@/features/maintenance/mimir-query-card";
import { RetentionCard } from "@/features/maintenance/retention-card";
import { ChannelAssignmentCard } from "@/features/notifications/channel-assignment";
import { RecipientsCard } from "@/features/notifications/notification-admin";

export function SettingsPage() {
  const { t } = useTranslation();

  return (
    <div>
      <PageHeader title={t("settings.title")} description={t("settings.description")} />

      <div className="space-y-6">
        <ChannelAssignmentCard />
        <RetentionCard />
        <MimirQueryCard />
        <SamlConfigCard />
        <LLMConfigCard />
        <RecipientsCard />
      </div>
    </div>
  );
}
