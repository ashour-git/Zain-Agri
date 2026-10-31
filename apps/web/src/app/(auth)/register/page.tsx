"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FormError, SubmitButton } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";

const schema = z
  .object({
    fullName: z
      .string()
      .trim()
      .min(2, { message: "الاسم يجب أن يكون حرفين على الأقل" })
      .max(200, { message: "الاسم طويل جداً" }),
    email: z.email({ message: "أدخل بريداً إلكترونياً صحيحاً" }),
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

export default function RegisterPage() {
  const { signUp } = useAuth();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { fullName: "", email: "", password: "", confirmPassword: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      await signUp(values.email.trim(), values.password, values.fullName.trim());
      router.replace("/select-tenant");
    } catch (error) {
      setFormError(
        error instanceof ApiRequestError
          ? error.message
          : "تعذّر إنشاء الحساب. تحقّق من الشبكة وحاول مجدداً.",
      );
    }
  });

  return (
    <Card className="border-white/10 bg-white/95 shadow-xl backdrop-blur">
      <CardHeader className="space-y-1 p-6 pb-2">
        <CardTitle className="text-lg">إنشاء حساب جديد</CardTitle>
        <CardDescription>
          أنشئ حسابك أولاً، ثم أنشئ متجرك لتصبح مالكه. خطوتان فقط.
        </CardDescription>
      </CardHeader>

      <CardContent className="p-6 pt-4">
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          <FormError>{formError}</FormError>

          <Field
            label="الاسم الكامل"
            autoComplete="name"
            placeholder="محمد أحمد"
            error={errors.fullName?.message}
            {...register("fullName")}
          />

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

          <SubmitButton type="submit" pending={isSubmitting}>
            {isSubmitting ? "جارٍ إنشاء الحساب…" : "إنشاء الحساب"}
          </SubmitButton>
        </form>

        <div className="mt-5 border-t border-line pt-4 text-xs text-ink-muted">
          لديك حساب بالفعل؟{" "}
          <a href="/login" className="font-semibold text-brand-700 hover:underline">
            تسجيل الدخول
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
