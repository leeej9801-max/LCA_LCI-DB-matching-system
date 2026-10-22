# D1 운영 이미지: uv.lock 그대로 설치, 비루트, fastapi run(dev 모드 아님)
# 경로 구성: 코드는 /app/Backend. 적재 도구가 코드 위치에서 두 단계 위(/app)를 기준으로 data/raw 를 찾는다
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/Backend/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.10.2
WORKDIR /app/Backend
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache
COPY . .
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8000
CMD ["fastapi", "run", "main.py", "--port", "8000"]
