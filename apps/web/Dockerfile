FROM node:22.22.0-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci

FROM node:22.22.0-bookworm-slim AS builder
WORKDIR /app
ENV ANALYSIS_URL=http://analysis:8000
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY . .
RUN npm run build

FROM node:22.22.0-bookworm-slim AS runner
ENV NODE_ENV=production
WORKDIR /app
RUN useradd --system --uid 1001 echora
COPY --from=builder --chown=echora /app/apps/web/.next/standalone ./
COPY --from=builder --chown=echora /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=echora /app/apps/web/public ./apps/web/public
USER echora
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
