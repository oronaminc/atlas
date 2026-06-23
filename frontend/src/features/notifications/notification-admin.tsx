/** Recipients (admin, view-only): users + their groups. Informational — incident
 *  fanout uses per-GROUP channels (Channel assignment), not these personal fields. */

import { useTranslation } from "react-i18next";

import { useRecipients } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function RecipientsCard() {
  const { t } = useTranslation();
  const recipients = useRecipients();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("notify.recipients")}</CardTitle>
        <CardDescription>{t("notify.recipientsHelp")}</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("common.name")}</TableHead>
              <TableHead>{t("auth.email")}</TableHead>
              <TableHead>Telegram</TableHead>
              <TableHead>{t("nav.groups")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(recipients.data?.data ?? []).map((r) => (
              <TableRow key={r.user_id}>
                <TableCell className="font-medium">{r.username}</TableCell>
                <TableCell className="text-muted-foreground">{r.email}</TableCell>
                <TableCell>
                  {r.telegram_chat_id ? (
                    <Badge variant="success">{r.telegram_chat_id}</Badge>
                  ) : (
                    <Badge variant="secondary">—</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {r.groups.map((g) => (
                      <Badge key={g} variant="outline">
                        {g}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
