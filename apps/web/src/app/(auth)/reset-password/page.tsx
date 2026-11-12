"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Field, FormError, SubmitButton } from "@/components/ui/field";
import { ApiRequestError, apiRequest } from "@/lib/api";

// Same rules as sign-up; the server checks them again.
const schema = z
  .object({
    password: z
      .string()
      .min(10, { message: "كلمة المرور يجب أن تكون 10 أحرف على الأقل" })
      .max(128, { message: "كلمة المرور طويلة جداً" })
      .refine((value) => !/^\d+$/.test(value), { message: "لا تستخدم أرقاماً فقط" }),
    confirmPassword: z.string(),
  })
  .refine((values) => values.password === values.confirmPassword, {
    message: "كلمتا المرور غير متطابقتين",
    path: ["confirmPassword"],
  });

type FormValues = z.infer<typeof schema>;

const MISSING_TOKEN =
  "الرابط ناقص. افتحه من رسالة تغيير كلمة المرور كما هو، أو اطلب رابطًا جديدًا.";

function ResetForm() {
  const token = useSearchParams().get("token");
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(token ? null : MISSING_TOKEN);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { password: "", confirmPassword: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    if (!token) return;
    setFormError(null);
    try {
      await apiRequest("/api/v1/auth/password-reset/confirm", {
        method: "POST",
        body: { token, new_password: values.password },
        anonymous: true,
      });
      router.replace("/login?reset=done");
    } catch (error) {
      setFormError(
        error instanceof ApiRequestError
          ? error.message
          : "تعذّر الاتصال بالخادم. تحقّق من الشبكة وحاول مجدداً.",
      );
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <FormError>{formError}</FormError>
      <Field
        label="كلمة المرور الجديدة"
        type="password"
        dir="ltr"
        autoComplete="new-password"
        placeholder="10 أحرف على الأقل"
        hint="استخدم كلمة مرور طويلة وفريدة. لا تُقبل الأرقام فقط."
        error={errors.password?.message}
        {...register("password")}
      />
      <Field
        label="تأكيد كلمة المرور"
        type="password"
        dir="ltr"
        autoComplete="new-password"
        placeholder="••••••••••"
        error={errors.confirmPassword?.message}
        {...register("confirmPassword")}
      />
      <SubmitButton type="submit" pending={isSubmitting} disabled={!token}>
        {isSubmitting ? "جارٍ الحفظ…" : "حفظ كلمة المرور"}
      </SubmitButton>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <Card className="border-0 bg-transparent">
      <CardHeader className="space-y-1.5 p-0 pb-7">
        <h1 className="text-[26px] font-semibold leading-tight text-ink">كلمة مرور جديدة</h1>
        <CardDescription>
          بعد الحفظ نُخرج حسابك من كل الأجهزة، ثم تسجّل الدخول بالكلمة الجديدة.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Suspense fallback={null}>
          <ResetForm />
        </Suspense>
        <div className="mt-6 border-t border-line pt-5 text-sm text-ink-muted">
          <a href="/forgot-password" className="font-semibold text-brand-700 hover:underline">
            اطلب رابطًا جديدًا
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
