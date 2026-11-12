"use client";

import { CircleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { FAILED_NIGHTS_BANNER, getBackup } from "@/lib/backup";

/** Owners only: the nightly backup has failed several nights in a row. */
export function BackupFailureBanner({ isOwner }: { isOwner: boolean }) {
  const [failedNights, setFailedNights] = useState(0);

  useEffect(() => {
    if (!isOwner) return;
    let cancelled = false;
    getBackup()
      .then((state) => {
        if (!cancelled && state.status === "active") setFailedNights(state.consecutive_failures);
      })
      .catch(() => {
        // A banner is a hint; never block the shell on it.
      });
    return () => {
      cancelled = true;
    };
  }, [isOwner]);

  if (failedNights < FAILED_NIGHTS_BANNER) return null;
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-2 border-b border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-800 sm:px-8"
    >
      <CircleAlert className="size-4 shrink-0" aria-hidden="true" />
      <span>لم تصل النسخة اليومية منذ {failedNights} ليالٍ.</span>
      <Link href="/settings/backup" className="font-semibold underline underline-offset-4">
        راجع الإعدادات
      </Link>
    </div>
  );
}
