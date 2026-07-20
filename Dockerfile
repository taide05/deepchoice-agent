# ===== Stage 1: Builder =====
FROM python:3.13-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY wheels/ /wheels/
COPY pyproject.toml README.md ./
COPY src/ src/

# 本地 wheels 优先（纯 Python 包跳过下载），平台不匹配的走清华镜像
RUN pip install --no-cache-dir --find-links=/wheels \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn .

COPY .build-hf-cache/hub/models--BAAI--bge-m3 /root/.cache/huggingface/hub/models--BAAI--bge-m3


# ===== Stage 2: Runtime =====
FROM python:3.13-slim

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface

COPY chroma_kb/ /app/chroma_kb/

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV HF_HUB_OFFLINE=1

EXPOSE 8000

ENTRYPOINT ["uvicorn", "deepchoice.server.app:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
