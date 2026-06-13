/** HQ-only tenant management: list subsidiaries + create (slug, name,
 *  Mimir orgs). The per-tenant ingest key is shown exactly once after
 *  creation — copy it then. */

import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useTenants } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import type { Envelope, Tenant } from "@/types";

export function TenantsCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const tenants = useTenants();

  const [createOpen, setCreateOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [orgs, setOrgs] = useState("");
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const create = useApiMutation(
    () =>
      api.post<Tenant>("/tenants", {
        slug,
        name,
        mimir_orgs: orgs
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    ["tenants"],
    (res: Envelope<Tenant>) => {
      setCreatedKey(res.data.ingest_key ?? null);
      setSlug("");
      setName("");
      setOrgs("");
    },
  );

  return (
    <Card data-testid="tenants-card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle className="text-base">{t("tenants.title")}</CardTitle>
          <CardDescription>{t("tenants.help")}</CardDescription>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="tenant-create">
          <Plus className="h-4 w-4" />
          {t("common.create")}
        </Button>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("tenants.slug")}</TableHead>
              <TableHead>{t("common.name")}</TableHead>
              <TableHead>{t("tenants.orgs")}</TableHead>
              <TableHead>{t("common.enabled")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(tenants.data?.data ?? []).map((tenant) => (
              <TableRow key={tenant.id} data-testid={`tenant-row-${tenant.slug}`}>
                <TableCell className="font-mono">{tenant.slug}</TableCell>
                <TableCell>{tenant.name}</TableCell>
                <TableCell className="space-x-1">
                  {tenant.mimir_orgs.map((org) => (
                    <Badge key={org} variant="outline">
                      {org}
                    </Badge>
                  ))}
                </TableCell>
                <TableCell>
                  <Badge variant={tenant.is_active ? "success" : "secondary"}>
                    {tenant.is_active ? "active" : "inactive"}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>

      <Dialog
        open={createOpen}
        onOpenChange={(open) => {
          setCreateOpen(open);
          if (!open) setCreatedKey(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("tenants.createTitle")}</DialogTitle>
          </DialogHeader>
          {createdKey ? (
            <div className="space-y-2" data-testid="tenant-ingest-key">
              <p className="text-sm">{t("tenants.keyOnce")}</p>
              <code className="block break-all rounded bg-muted p-2 text-xs">{createdKey}</code>
            </div>
          ) : (
            <div className="space-y-3">
              <div>
                <Label htmlFor="tenant-slug">{t("tenants.slug")}</Label>
                <Input
                  id="tenant-slug"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="sub-a"
                />
              </div>
              <div>
                <Label htmlFor="tenant-name">{t("common.name")}</Label>
                <Input id="tenant-name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="tenant-orgs">{t("tenants.orgsHelp")}</Label>
                <Input
                  id="tenant-orgs"
                  value={orgs}
                  onChange={(e) => setOrgs(e.target.value)}
                  placeholder="org-a, org-a-dr"
                />
              </div>
            </div>
          )}
          <DialogFooter>
            {createdKey ? (
              <Button onClick={() => setCreateOpen(false)}>{t("common.close")}</Button>
            ) : (
              <Button
                onClick={() =>
                  create.mutate(undefined, {
                    onError: (e) =>
                      toast({
                        variant: "destructive",
                        title: t("common.failed"),
                        description: e instanceof Error ? e.message : String(e),
                      }),
                  })
                }
                disabled={!slug || !name || create.isPending}
                data-testid="tenant-save"
              >
                {t("common.save")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
