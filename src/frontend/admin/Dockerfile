# syntax=docker/dockerfile:1
# Nuxt 4 SSR build -> Node server output (.output/server/index.mjs).
# admin chạy dưới sub-path /admin/ : base URL set lúc runtime qua NUXT_APP_BASE_URL
# (compose), không cần build lại khi đổi path.

FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV NITRO_HOST=0.0.0.0
ENV NITRO_PORT=3001
COPY --from=build /app/.output ./.output
EXPOSE 3001
CMD ["node", ".output/server/index.mjs"]
