/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Catalyst Web Client Hosting serves static files, so the console ships as a static
  // export. Legal here because every component is "use client" — there is no server
  // action, route handler or SSR data fetch in the app. `next start` still works.
  output: "export",
  images: { unoptimized: true },   // no Next image optimizer without a Node server
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};
export default nextConfig;
