FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# Subpath base, baked into asset URLs at build (same value dev+prod, e.g.
# /alert-hub/). Default "/" builds for root. Set via build-arg in CI/overlays.
ARG VITE_BASE_PATH=/
ENV VITE_BASE_PATH=$VITE_BASE_PATH
RUN pnpm build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# The official nginx entrypoint envsubsts /etc/nginx/templates/*.template
# into /etc/nginx/conf.d/, substituting only variables that are set in the
# environment — nginx's own $host etc. are left intact.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_ORIGIN=http://backend:8000
EXPOSE 80
