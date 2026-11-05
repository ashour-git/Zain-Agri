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

const schema = z.object({
  email: z.email({ message: "أدخل بريداً إلكترونياً صحيحاً" }),
  password: z.string().min(1, { message: "أدخل كلمة المرور" }),
});

type FormValues = z.infer<typeof schema>;

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
    <Card className="border-white/10 bg-white/95 shadow-xl backdrop-blur">
      <CardHeader className="space-y-1 p-6 pb-2">
        <CardTitle className="text-lg">تسجيل الدخول</CardTitle>
        <CardDescription>ادخل إلى مساحة عمل متجرك باستخدام بريدك وكلمة المرور.</CardDescription>
      </CardHeader>

      <CardContent className="p-6 pt-4">
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

          <Field
            label="كلمة المرور"
            type="password"
            dir="ltr"
            autoComplete="current-password"
            placeholder="••••••••••"
            error={errors.password?.message}
            {...register("password")}
          />

          <SubmitButton type="submit" pending={isSubmitting}>
            {isSubmitting ? "جارٍ التحقق…" : "دخول"}
          </SubmitButton>
        </form>

        <div className="mt-5 space-y-3 border-t border-line pt-4 text-xs text-ink-muted">
          <p>
            ليس لديك حساب؟{" "}
            <a href="/register" className="font-semibold text-brand-700 hover:underline">
              أنشئ متجرك الآن
            </a>
          </p>
          <p className="leading-relaxed text-xs">
            نستخدم ملف تعريف ارتباط HttpOnly لجلسة التجديد، ولا نحفظ رموز الدخول في المتصفح.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
