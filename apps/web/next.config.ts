import type { NextConfig } from "next";

/*
 * The browser only ever talks to this app's own origin; /api/* is proxied to
 * the API server. The refresh token is an HttpOnly, SameSite=Lax cookie, so
 * the web app and the API must look like one site to the browser. On separate
 * domains (e.g. *.vercel.app and *.northflank.app) the cookie would never be
 * sent and every reload would log the user out.
 *
 * API_ORIGIN is read on the server at build/run time, never shipped to the
 * browser. Locally it defaults to the dev API.
 */
const apiOrigin = (process.env.API_ORIGIN ?? "http://localhost:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
