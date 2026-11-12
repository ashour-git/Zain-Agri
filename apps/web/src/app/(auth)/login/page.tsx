"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Field, FormError, FormNotice, SubmitButton } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";

const schema = z.object({
  email: z.email({ message: "أدخل بريداً إلكترونياً صحيحاً" }),
  password: z.string().min(1, { message: "أدخل كلمة المرور" }),
});

type FormValues = z.infer<typeof schema>;

/** Shown after a successful password reset (/login?reset=done). */
function ResetNotice() {
  const done = useSearchParams().get("reset") === "done";
  return (
    <FormNotice>{done ? "تم تغيير كلمة المرور. سجّل الدخول بالكلمة الجديدة." : null}</FormNotice>
  );
}

export default function LoginPage() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      const session = await signIn(values.email.trim(), values.password);
      router.replace(session.requires_tenant_selection ? "/select-tenant" : "/");
    } catch (error) {
      setFormError(
        error instanceof ApiRequestError
          ? error.message
          : "تعذّر الاتصال بالخادم. تحقّق من الشبكة وحاول مجدداً.",
      );
    }
  });

  return (
    <Card className="border-0 bg-transparent">
      <CardHeader className="space-y-1.5 p-0 pb-7">
        <h1 className="text-[26px] font-semibold leading-tight text-ink">الدخول إلى متجرك</h1>
        <CardDescription>استخدم البريد الإلكتروني وكلمة المرور الخاصة بحسابك.</CardDescription>
      </CardHeader>

      <CardContent className="p-0">
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <Suspense fallback={null}>
            <ResetNotice />
          </Suspense>
          <FormError>{formError}</FormError>

          <Field
            label="البريد الإلكتروني"
            type="email"
            dir="ltr"
            autoComplete="email"
            placeholder="owner@example.com"
            error={errors.email?.message}
            {...register("email")}
          />

          <Field
            label="كلمة المرور"
            type="password"
            dir="ltr"
            autoComplete="current-password"
            placeholder="••••••••••"
            error={errors.password?.message}
            {...register("password")}
          />

          <p className="-mt-2 text-end text-[13px]">
            <a href="/forgot-password" className="font-medium text-brand-700 hover:underline">
              نسيت كلمة المرور؟
            </a>
          </p>

          <SubmitButton type="submit" pending={isSubmitting}>
            {isSubmitting ? "جارٍ الدخول…" : "تسجيل الدخول"}
          </SubmitButton>
        </form>

        <div className="mt-6 space-y-3 border-t border-line pt-5 text-sm text-ink-muted">
          <p>
            تفتح متجرًا جديدًا؟{" "}
            <a href="/register" className="font-semibold text-brand-700 hover:underline">
              أنشئ حسابًا
            </a>
          </p>
          <p className="leading-relaxed text-[13px]">
            جلستك مشفّرة، ولا تُحفظ كلمة المرور على هذا الجهاز.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
