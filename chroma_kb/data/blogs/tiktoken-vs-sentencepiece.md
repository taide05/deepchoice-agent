# Tiktoken vs SentencePiece

**Category**: Models & Data
**Expected winner**: Tiktoken

## Analysis

Tiktoken is faster (Rust implementation), is used by OpenAI models (GPT-4, GPT-4o), and has a simpler API for counting tokens. SentencePiece is more flexible (supports BPE and unigram) and is used by many open-source models. For production OpenAI-compatible pipelines, Tiktoken is the better choice.

## Known Contradictions

### Model compatibility
- Position A: SentencePiece supports more tokenization algorithms and is model-agnostic
- Position B: For OpenAI-compatible APIs, Tiktoken's token counts match the API billing exactly — SentencePiece estimates will drift
