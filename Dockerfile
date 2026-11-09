# ===== Stage 1: Builder =====
FROM python:3.13-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY pyproject.toml README.md ./
COPY src/ src/

# Online install via the Tsinghua mirror — no local wheels directory is
# required, so `git clone && docker build` works out of the box.
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn .


# ===== Stage 2: Runtime =====
FROM python:3.13-slim

# CJK font for PDF report export (xhtml2pdf). fonts-wqy-zenhei is TrueType-outlined
# (reportlab can open it with subfontIndex=0); NotoSansCJK is CFF-based and cannot.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY chroma_kb/ /app/chroma_kb/

WORKDIR /app

ENV PYTHONUNBUFFERED=1

# BGE-M3 downloads on first use (~2GB) into the HF cache; mount a volume at
# /root/.cache/huggingface to persist it across container restarts.

EXPOSE 8000

ENTRYPOINT ["uvicorn", "deepchoice.server.app:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
