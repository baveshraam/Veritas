/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Catalyst Web Client Hosting serves static files, so the console ships as a static
  // export. Legal here because every component is "use client" — there is no server
  // action, route handler or SSR data fetch in the app. `next start` still works.
  output: "export",
  // Catalyst serves the client bundle from /app/, not the domain root, so the default
  // root-relative /_next/... asset URLs 404 and the page never hydrates. Prefix them.
  assetPrefix: "/app",
  images: { unoptimized: true },   // no Next image optimizer without a Node server
  env: {
    // Defaults to the deployed API, not localhost: this is a static export, so whatever is
    // here at build time is what ships to every user's browser. A wrong default is invisible
    // in dev and fatal in production (the page just hangs), so production is the safe default.
    // For a local API: NEXT_PUBLIC_API_URL=http://localhost:8000 in apps/web/.env.local
    NEXT_PUBLIC_API_URL:
      process.env.NEXT_PUBLIC_API_URL ??
      "https://veritas-api-50043864344.development.catalystappsail.in",
    // Mirrors `assetPrefix` below, for the public/ images `<img src>` references
    // directly — see lib/asset.ts. Same "production wins the default" rule.
    NEXT_PUBLIC_ASSET_PREFIX: process.env.NEXT_PUBLIC_ASSET_PREFIX ?? "/app",
  },
};
export default nextConfig;
