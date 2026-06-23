/** SAML SSO config: SP key/cert + IdP metadata + attribute mapping. Admin-only
 *  (/settings is gated). The private key shows ******** when set; leaving it
 *  unchanged preserves the stored key (backend ignores the mask). */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation } from "@/api/queries";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";

interface SamlCfg {
  enabled: boolean;
  sp_private_key: string | null;
  sp_certificate: string | null;
  idp_metadata_xml: string | null;
  display_name_attr: string;
  uid_attr: string;
  email_attr: string;
}

export function SamlConfigCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const config = useQuery({
    queryKey: ["saml-config"],
    queryFn: () => api.get<SamlCfg>("/saml-config"),
  });

  const [form, setForm] = useState<SamlCfg | null>(null);
  useEffect(() => {
    if (config.data) setForm(config.data.data);
  }, [config.data]);

  const save = useApiMutation(
    () => api.patch<SamlCfg>("/saml-config", form),
    ["saml-config"],
    () => toast({ title: t("common.success") }),
  );

  if (!form) return null;
  const set = <K extends keyof SamlCfg>(k: K, v: SamlCfg[K]) => setForm({ ...form, [k]: v });

  return (
    <Card className="max-w-xl" data-testid="saml-config-card">
      <CardHeader>
        <CardTitle className="text-base">{t("saml.title")}</CardTitle>
        <CardDescription>{t("saml.help")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Switch
            id="saml-enabled"
            checked={form.enabled}
            onCheckedChange={(v) => set("enabled", v)}
          />
          <Label htmlFor="saml-enabled">{t("saml.enabled")}</Label>
        </div>
        <div>
          <Label htmlFor="saml-key">{t("saml.spPrivateKey")}</Label>
          <Textarea
            id="saml-key"
            rows={4}
            value={form.sp_private_key ?? ""}
            placeholder={t("saml.spPrivateKeyHelp")}
            onChange={(e) => set("sp_private_key", e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="saml-cert">{t("saml.spCertificate")}</Label>
          <Textarea
            id="saml-cert"
            rows={4}
            value={form.sp_certificate ?? ""}
            onChange={(e) => set("sp_certificate", e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="saml-idp">{t("saml.idpMetadata")}</Label>
          <Textarea
            id="saml-idp"
            rows={6}
            value={form.idp_metadata_xml ?? ""}
            onChange={(e) => set("idp_metadata_xml", e.target.value)}
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label htmlFor="saml-dn">{t("saml.displayNameAttr")}</Label>
            <Input
              id="saml-dn"
              value={form.display_name_attr}
              onChange={(e) => set("display_name_attr", e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="saml-uid">{t("saml.uidAttr")}</Label>
            <Input
              id="saml-uid"
              value={form.uid_attr}
              onChange={(e) => set("uid_attr", e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="saml-email">{t("saml.emailAttr")}</Label>
            <Input
              id="saml-email"
              value={form.email_attr}
              onChange={(e) => set("email_attr", e.target.value)}
            />
          </div>
        </div>
        <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>
          {t("common.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
