/** Catalyst serves this console from /app/, not the domain root (see next.config.mjs's
 *  `assetPrefix`) — but that setting only rewrites Next's OWN emitted `_next/...` chunk
 *  URLs. A plain `<img src="/x.svg">` is untouched by it and would 404 in production the
 *  same way the v9 bug did for the JS bundle. `NEXT_PUBLIC_ASSET_PREFIX` mirrors
 *  `assetPrefix` for our own `public/` references; production wins the default, the same
 *  rule `NEXT_PUBLIC_API_URL` already follows, for the same reason. */
export function assetUrl(path: string): string {
  return `${process.env.NEXT_PUBLIC_ASSET_PREFIX ?? "/app"}${path}`;
}
