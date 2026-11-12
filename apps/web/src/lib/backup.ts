/** Daily backup email: typed calls for the owner settings and the confirm link. */

import { apiRequest } from "@/lib/api";

export type BackupStatus = "pending" | "active" | "stopped";

export type BackupState = {
  email: string | null;
  status: BackupStatus | null;
  last_sent_at: string | null;
  last_error_ar: string | null;
  consecutive_failures: number;
  manual_sends_left: number;
  mail_configured: boolean;
};

const PATH = "/api/v1/tenants/current/backup";

/** Shown in the app shell to owners when this many nights failed in a row. */
export const FAILED_NIGHTS_BANNER = 3;

export const getBackup = () => apiRequest<BackupState>(PATH);

export const saveBackupEmail = (email: string) =>
  apiRequest<BackupState>(PATH, { method: "PUT", body: { email } });

export const sendBackupNow = () => apiRequest<BackupState>(`${PATH}/send`, { method: "POST" });

export const stopBackup = () => apiRequest<void>(PATH, { method: "DELETE" });

export const confirmBackupEmail = (token: string) =>
  apiRequest<void>("/api/v1/backup/confirm", {
    method: "POST",
    body: { token },
    anonymous: true,
  });

const SENT_AT = new Intl.DateTimeFormat("ar-EG-u-nu-latn", {
  weekday: "long",
  day: "numeric",
  month: "long",
  hour: "numeric",
  minute: "2-digit",
  timeZone: "Africa/Cairo",
});

export function formatSentAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : SENT_AT.format(date);
}
