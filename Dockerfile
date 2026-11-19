# ===== Stage 1: Builder =====
# Python 3.12 matches .github/workflows/ci.yml. A 3.13 CI matrix is tracked
# separately and must not be mixed into this alignment.
FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

# Online install through a configurable index (default: the Tsinghua mirror used
# locally). CI overrides it with the public PyPI so the required image job does
# not depend on a single mirror's reachability.
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
RUN pip install --no-cache-dir \
    -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST" .


# ===== Stage 2: Runtime =====
FROM python:3.12-slim

# CJK font for PDF report export (xhtml2pdf). fonts-wqy-zenhei is TrueType-outlined
# (reportlab can open it with subfontIndex=0); NotoSansCJK is CFF-based and cannot.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY chroma_kb/ /app/chroma_kb/

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# BGE-M3 downloads on first use (~2GB) into the HF cache; mount a volume at
# /root/.cache/huggingface to persist it across container restarts.

EXPOSE 8000

ENTRYPOINT ["uvicorn", "deepchoice.server.app:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
