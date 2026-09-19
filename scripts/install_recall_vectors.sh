#!/usr/bin/env bash
# Engram — install the OPTIONAL local meaning-search sidecar for `recall`.
#
# Everything is pinned and verified: the model file is checked against the
# sha256 Hugging Face records for this exact revision, and the Python packages
# are pinned by version. Nothing runs remotely afterwards; embeddings are
# computed on this machine. Re-running is safe (skips what's already present).
#
#   scripts/install_recall_vectors.sh          # ~135 MB model + ~40 MB wheels
#   python3 scripts/recall.py --rebuild-vectors   # then embed the vault once
set -euo pipefail

HOME_DIR="${ENGRAM_EMBED_HOME:-$HOME/.cache/engram-embed}"
MODEL_DIR="$HOME_DIR/bge-small-en-v1.5"
REPO="BAAI/bge-small-en-v1.5"                      # MIT licence
REV="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
ONNX_SHA256="828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35"
PY_PKGS=("onnxruntime==1.22.1" "tokenizers==0.21.4" "numpy==2.2.6")

command -v uv >/dev/null || { echo "needs uv (https://docs.astral.sh/uv/)" >&2; exit 1; }
mkdir -p "$MODEL_DIR"

if [ ! -x "$HOME_DIR/venv/bin/python" ]; then
  uv venv -q -p 3.12 "$HOME_DIR/venv"
fi
uv pip install -q -p "$HOME_DIR/venv/bin/python" "${PY_PKGS[@]}"

for f in onnx/model.onnx tokenizer.json config.json; do
  dest="$MODEL_DIR/$(basename "$f")"
  [ -s "$dest" ] || curl -sfL -o "$dest" "https://huggingface.co/$REPO/resolve/$REV/$f"
done
got=$(shasum -a 256 "$MODEL_DIR/model.onnx" | cut -d' ' -f1)
if [ "$got" != "$ONNX_SHA256" ]; then
  echo "model.onnx sha256 mismatch ($got) — refusing to use it" >&2
  mv "$MODEL_DIR/model.onnx" "$MODEL_DIR/model.onnx.rejected"
  exit 1
fi
echo "$REV" > "$MODEL_DIR/REVISION"
echo "installed: $MODEL_DIR (rev ${REV:0:8}, sha256 verified)"
echo "next: python3 scripts/recall.py --rebuild-vectors"
