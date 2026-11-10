import type { NextConfig } from "next";

/*
 * The browser only ever talks to this site's own origin and calls /api/*.
 * The refresh token is an HttpOnly, SameSite=Lax cookie, so the website and
 * the API must look like one site to the browser.
 *
 * - On Vercel (services mode, see /vercel.json) the platform routes /api/* to
 *   the `api` service before this app sees the request: no rewrite here.
 * - Locally (`pnpm dev`) this app proxies /api/* to API_ORIGIN instead.
 *   `vercel dev` runs both services and routes like production.
 */
const apiOrigin = (process.env.API_ORIGIN ?? "http://localhost:8000").replace(/\/+$/, "");
const onVercel = Boolean(process.env.VERCEL);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    if (onVercel) return [];
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
