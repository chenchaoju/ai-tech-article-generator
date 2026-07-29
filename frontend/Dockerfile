FROM docker.m.daocloud.io/library/node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_PUBLIC_BASE=/article-workshop/
ARG VITE_API_BASE_URL=/article-workshop/api
ENV VITE_PUBLIC_BASE=${VITE_PUBLIC_BASE} \
    VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM docker.m.daocloud.io/library/nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
