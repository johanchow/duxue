FROM node:22.21.1-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npx --no-install esbuild scripts/setup.ts --bundle --platform=node --format=cjs --external:pg-native --external:cloudflare:sockets --outfile=ops/setup.cjs

RUN mkdir -p /app/public

FROM node:22.21.1-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
COPY --from=build --chown=node:node /app/public ./public
COPY --from=build --chown=node:node /app/migrations ./migrations
COPY --from=build --chown=node:node /app/ops ./ops
USER node
EXPOSE 3000
CMD ["node", "server.js"]
