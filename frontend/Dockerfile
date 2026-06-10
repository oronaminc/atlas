FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# The official nginx entrypoint envsubsts /etc/nginx/templates/*.template
# into /etc/nginx/conf.d/, substituting only variables that are set in the
# environment — nginx's own $host etc. are left intact.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_ORIGIN=http://backend:8000
EXPOSE 80
