"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Field, FormError, FormNotice, SubmitButton } from "@/components/ui/field";
import { ApiRequestError, apiRequest } from "@/lib/api";

const schema = z.object({
  email: z.email({ message: "أدخل بريداً إلكترونياً صحيحاً" }),
});

type FormValues = z.infer<typeof schema>;

// Identical for every address: the page must not reveal who has an account.
const SENT =
  "إذا كان البريد مسجّلًا لدينا، ستصلك رسالة فيها رابط لتغيير كلمة المرور خلال دقائق. الرابط صالح لمدة 30 دقيقة. راجع مجلد الرسائل غير المرغوب فيها إن لم تجدها.";

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { email: "" } });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await apiRequest("/api/v1/auth/password-reset/request", {
        method: "POST",
        body: { email: values.email.trim() },
        anonymous: true,
      });
      setSent(true);
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
        <h1 className="text-[26px] font-semibold leading-tight text-ink">نسيت كلمة المرور</h1>
        <CardDescription>
          أدخل البريد الذي تسجّل به الدخول، وسنرسل إليه رابطًا لاختيار كلمة مرور جديدة.
        </CardDescription>
      </CardHeader>

      <CardContent className="p-0">
        {sent ? (
          <FormNotice>{SENT}</FormNotice>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
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
            <SubmitButton type="submit" pending={isSubmitting}>
              {isSubmitting ? "جارٍ الإرسال…" : "إرسال رابط التغيير"}
            </SubmitButton>
          </form>
        )}

        <div className="mt-6 border-t border-line pt-5 text-sm text-ink-muted">
          <a href="/login" className="font-semibold text-brand-700 hover:underline">
            العودة إلى تسجيل الدخول
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
