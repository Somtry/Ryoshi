# Ryoshi 后端镜像:Python 3.12 + uv + FastAPI(uvicorn)。
#
# 配置统一来自仓库根目录 .env.local(config.py 按代码路径向上锚定到
# /app/.env.local),因此构建上下文必须是仓库根;运行时也可被
# docker-compose 的 environment 覆盖(如容器内 DATABASE_URL)。

FROM python:3.12-slim

# uv:依赖安装与虚拟环境管理
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 先拷依赖清单(利用层缓存),装到系统 Python(容器内无需 venv)
COPY apps/server/pyproject.toml apps/server/uv.lock apps/server/
RUN cd apps/server && uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3

# 再拷源码、迁移脚本与根目录环境文件
COPY apps/server/ apps/server/
COPY .env.local .env.local

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# 启动前执行数据库迁移,再拉起 uvicorn
# (ryoshi.main:app 见 apps/server/src/ryoshi/main.py)
#
# --proxy-headers + --forwarded-allow-ips:生产流量经 nginx 反代,
# 必须信任代理头(X-Forwarded-For/X-Real-IP),否则 request.client.host
# 拿到的是 nginx 容器 IP,云端访客限流会把所有匿名用户合进同一个桶
# (每天 10 次全站共享)。compose 内网只有 nginx 能直达 server,
# 允许整个内网段信任是安全的。
CMD ["/bin/sh", "-c", "cd apps/server && uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn ryoshi.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='10.0.0.0/8 172.16.0.0/12 192.168.0.0/16'"]
