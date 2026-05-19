# MES 前端 Dockerfile
# 多阶段构建：第一阶段编译，第二阶段用 Nginx 提供静态服务
# 启用 BuildKit cache mounts 加速重复构建
# 注意：build context 应为 mes-frontend/ 目录

# --- 构建阶段 ---
FROM node:20-slim AS builder

WORKDIR /app

# 先复制 package 文件，利用 Docker 层缓存加速重复构建
COPY package.json package-lock.json* ./

# 安装依赖（带 npm cache mount）
RUN --mount=type=cache,target=/root/.npm \
    npm config set registry https://registry.npmmirror.com && npm ci --ignore-platform

COPY . ./

ARG VITE_API_BASE=
ENV VITE_API_BASE=${VITE_API_BASE}

# 构建（带 vite cache mount）
RUN --mount=type=cache,target=/app/node_modules/.cache \
    npm run build

# --- 生产阶段 ---
FROM nginx:1.25-alpine AS production

# 复制 Nginx envsubst 模板（在启动时通过 envsubst 渲染）
COPY nginx.conf /etc/nginx/nginx.conf.template

# 启动前渲染模板并启动 nginx
RUN echo '#!/bin/sh\nset -e\nenvsubst < /etc/nginx/nginx.conf.template > /etc/nginx/conf.d/default.conf\nexec nginx -g "daemon off;"' > /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

# 将构建产物复制到 Nginx 静态目录
COPY --from=builder /app/dist /usr/share/nginx/html

# N-P1-27: Run Nginx as non-root user for security
RUN chown -R nginx:nginx /var/cache/nginx /var/log/nginx /var/run && \
    chown -R nginx:nginx /usr/share/nginx/html && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid
USER nginx

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ || exit 1

EXPOSE 80

CMD ["/docker-entrypoint.sh"]
