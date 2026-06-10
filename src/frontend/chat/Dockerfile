# syntax=docker/dockerfile:1
# Nuxt 4 SSR build -> Node server output (.output/server/index.mjs).
# Multi-stage: build cần devDependencies (vite/tailwind); runtime chỉ cần .output.

FROM node:20-alpine AS build
WORKDIR /app
# Cài theo lockfile để reproducible. postinstall chạy `nuxt prepare`.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
# Nitro đọc HOST/PORT lúc runtime. PORT override được ở compose nếu cần.
ENV NITRO_HOST=0.0.0.0
ENV NITRO_PORT=3000
COPY --from=build /app/.output ./.output
EXPOSE 3000
CMD ["node", ".output/server/index.mjs"]
