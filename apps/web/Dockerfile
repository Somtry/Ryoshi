# Ryoshi 前端镜像:Vite 构建产物 + Nginx 托管,/api 与 /relay 反代到 server。
#
# 配置统一来自仓库根目录 .env.local(见 vite.config.ts 的 envDir),
# 因此构建上下文必须是仓库根,VITE_* 变量在构建时内联进产物。

# ---- 构建阶段 ----
FROM node:22-alpine AS build
WORKDIR /repo

RUN corepack enable

# 先拷清单装依赖(利用层缓存)
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml apps/web/
RUN cd apps/web && pnpm install --frozen-lockfile

# 再拷源码与根目录环境文件并构建
COPY apps/web/ apps/web/
COPY .env.local .env.local
RUN cd apps/web && pnpm build

# ---- 运行阶段 ----
FROM nginx:alpine
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
