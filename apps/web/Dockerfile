# AstraForce web (Next.js) — üretim imajı. Derleme bağlamı: depo kökü.
FROM node:24-alpine AS build
RUN corepack enable && corepack prepare pnpm@10.4.1 --activate
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/api/package.json apps/api/package.json
RUN pnpm install --frozen-lockfile --filter web...
COPY apps/web apps/web
# Tarayıcı API'yi hep aynı alan adından çağırır: /api/*
#  - docker-compose.prod.yml: Caddy /api → api:8000 yönlendirir
#  - Render: API_HOSTPORT (API'nin iç ağ adresi, ör. astraforce-api:10000) verilir; Next.js
#    /api/* isteklerini oraya aktarır (next.config.ts rewrites)
ARG NEXT_PUBLIC_API_URL=/api
ARG API_HOSTPORT=
ARG NEXT_PUBLIC_DEFAULT_LOCALE=en
ARG NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_DEFAULT_LOCALE=$NEXT_PUBLIC_DEFAULT_LOCALE \
    NEXT_PUBLIC_MAP_STYLE_URL=$NEXT_PUBLIC_MAP_STYLE_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN if [ -n "$API_HOSTPORT" ]; then export API_INTERNAL_URL="http://$API_HOSTPORT"; fi \
    && echo "API_INTERNAL_URL=${API_INTERNAL_URL:-<yok, /api dış yönlendirmeyle>}" \
    && pnpm --filter web build

FROM node:24-alpine
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
