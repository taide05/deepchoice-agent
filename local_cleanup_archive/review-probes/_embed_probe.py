"""Load the local embedding model fully offline, then report index state."""
import os
import pathlib
import sys

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

ROOT = pathlib.Path(r"D:\deepchoice-precodex")
target = ROOT / "chroma_kb" / "chroma_db"
print("chroma_db exists before build:", target.exists())

from sentence_transformers import SentenceTransformer

model = SentenceTransformer("BAAI/bge-m3")
vector = model.encode(["offline check"])
print("model loaded offline:", type(model).__name__)
print("embedding dimension :", len(vector[0]))
