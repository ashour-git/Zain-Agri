"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Building2, Check, LogOut, PlusCircle, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthGuard } from "@/components/auth/auth-guard";
import { BrandMark, BrandWordmark } from "@/components/brand";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FormError, SubmitButton } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { ROLE_LABELS, type TenantMembership } from "@/lib/types";

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(2, { message: "اسم المتجر يجب أن يكون حرفين على الأقل" })
    .max(200, { message: "اسم المتجر طويل جداً" }),
});

type FormValues = z.infer<typeof schema>;

function WorkspaceRow({
  workspace,
  busy,
  onSelect,
}: {
  workspace: TenantMembership;
  busy: boolean;
  onSelect: () => void;
}) {
  // A suspended workspace or a non-active membership is visible but not
  // enterable — the server would refuse the rotation, so the button is disabled
  // instead of failing after a round trip.
  const blocked = workspace.status !== "active" || workspace.membership_status !== "active";

  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={busy || blocked}
      className="flex w-full items-center gap-3 rounded-md border border-line bg-white px-4 py-3 text-start transition
                 hover:border-brand-300 hover:bg-brand-50/40 disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
        <Building2 className="size-5" aria-hidden="true" />
      </span>

      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-ink">{workspace.name}</span>
        <span className="hidden">
          {workspace.slug}
        </span>
      </span>

      <span className="flex shrink-0 items-center gap-2">
        <Badge variant="brand">{ROLE_LABELS[workspace.role]}</Badge>
        {workspace.status !== "active" ? (
          <Badge variant="danger">
            <ShieldAlert className="size-3" aria-hidden="true" />
            موقوفة
          </Badge>
        ) : workspace.membership_status !== "active" ? (
          <Badge variant="warning">
            عضوية غير نشطة
          </Badge>
        ) : (
          <Check className="size-4 text-brand-600" aria-hidden="true" />
        )}
      </span>
    </button>
  );
}

function SelectTenantContent() {
  const { session, switchWorkspace, createWorkspace, signOut } = useAuth();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "" },
  });

  const workspaces = session?.tenants ?? [];

  const onSelect = async (workspace: TenantMembership) => {
    setFormError(null);
    setSelecting(workspace.id);
    try {
      await switchWorkspace(workspace.id);
      router.replace("/");
    } catch (error) {
      setFormError(
        error instanceof ApiRequestError
          ? error.message
          : "تعذّر فتح مساحة العمل. تحقّق من الشبكة وحاول مجدداً.",
      );
    } finally {
      setSelecting(null);
    }
  };

  const onCreate = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await createWorkspace(values.name.trim());
      reset();
      router.replace("/");
    } catch (error) {
      setFormError(
        error instanceof ApiRequestError
          ? error.message
          : "تعذّر إنشاء مساحة العمل. حاول مرة أخرى.",
      );
    }
  });

  return (
    <div className="min-h-dvh bg-surface">
      <div className="relative mx-auto flex min-h-dvh w-full max-w-xl flex-col px-5 py-8 sm:px-8">
        <div className="flex items-center gap-3">
          <BrandMark />
          <BrandWordmark />
          <button
            type="button"
            onClick={() => {
              void signOut().then(() => router.replace("/login"));
            }}
            className="ms-auto inline-flex min-h-10 items-center gap-2 rounded-md px-3 text-sm text-ink-muted transition-colors hover:bg-red-50 hover:text-red-700"
          >
            <LogOut className="size-3.5" aria-hidden="true" />
            تسجيل الخروج
          </button>
        </div>

        <div className="flex flex-1 items-center justify-center py-10">
          <div className="w-full space-y-5">
            <div className="space-y-1 text-center">
              <h1 className="text-[26px] font-semibold text-ink">اختر مساحة عمل</h1>
              <p className="text-sm text-ink-muted">
                مرحباً {session?.user.full_name || "بك"}،{" "}
                {workspaces.length === 0
                  ? "أنشئ متجرك الأول للبدء."
                  : "اختر المتجر الذي تريد العمل عليه."}
              </p>
            </div>

            <Card>
              <CardHeader className="p-5 pb-3">
                <CardTitle className="text-sm">متاجرك</CardTitle>
                <CardDescription>يظهر هنا كل متجر أنت عضو فيه.</CardDescription>
              </CardHeader>

              <CardContent className="space-y-2.5 p-5 pt-0">
                <FormError>{formError}</FormError>

                {workspaces.length === 0 ? (
                  <p className="rounded-md border border-dashed border-line px-4 py-6 text-center text-xs text-ink-muted">
                    لا توجد متاجر بعد. أنشئ متجرك الأول من النموذج أدناه.
                  </p>
                ) : (
                  workspaces.map((workspace) => (
                    <WorkspaceRow
                      key={workspace.id}
                      workspace={workspace}
                      busy={selecting !== null}
                      onSelect={() => {
                        void onSelect(workspace);
                      }}
                    />
                  ))
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="p-5 pb-3">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <PlusCircle className="size-4 text-brand-600" aria-hidden="true" />
                  إنشاء متجر جديد
                </CardTitle>
                <CardDescription>
                  ستصبح مالك المتجر الجديد فوراً، ويمكنك دعوة فريقك لاحقاً.
                </CardDescription>
              </CardHeader>

              <CardContent className="p-5 pt-0">
                <form onSubmit={onCreate} className="space-y-3" noValidate>
                  <Field
                    label="اسم المتجر"
                    placeholder="مؤسسة زين الزراعية"
                    autoComplete="organization"
                    error={errors.name?.message}
                    {...register("name")}
                  />
                  <SubmitButton type="submit" pending={isSubmitting}>
                    {isSubmitting ? "جارٍ الإنشاء…" : "إنشاء المتجر"}
                  </SubmitButton>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>

        <p className="text-center text-xs text-ink-muted">
          ZAIN AGRI - اتصال آمن
        </p>
      </div>
    </div>
  );
}

export default function SelectTenantPage() {
  return (
    <AuthGuard requireTenant={false}>
      <SelectTenantContent />
    </AuthGuard>
  );
}
