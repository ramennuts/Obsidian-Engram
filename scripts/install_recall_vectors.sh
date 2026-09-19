#!/usr/bin/env bash
# Engram — install the OPTIONAL local meaning-search sidecar for `recall`.
#
# Both files the sidecar reads are pinned to one Hugging Face revision and
# sha256-verified (model.onnx against HF's recorded LFS sha256; tokenizer.json
# against a sha256 taken from a copy whose git blob id matched HF's record).
# A mismatch is renamed *.rejected and the install fails. Python packages are
# pinned by version (not by hash). Nothing runs remotely afterwards; embeddings are
# computed on this machine. Re-running is safe (skips what's already present).
#
#   scripts/install_recall_vectors.sh          # ~135 MB model + ~40 MB wheels
#   python3 scripts/recall.py --rebuild-vectors   # then embed the vault once
set -euo pipefail

HOME_DIR="${ENGRAM_EMBED_HOME:-$HOME/.cache/engram-embed}"
MODEL_DIR="$HOME_DIR/bge-small-en-v1.5"
REPO="BAAI/bge-small-en-v1.5"                      # MIT licence
REV="5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
# A function, not an associative array: macOS ships bash 3.2, where
# `declare -A` fails and an unset lookup would compare against "" (the first
# draft of this script printed "verified" without checking anything).
expected_sha256() {
  case "$1" in
    model.onnx)     echo "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35" ;;
    tokenizer.json) echo "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66" ;;
    *) echo "no pinned hash for $1" >&2; exit 1 ;;
  esac
}
PY_PKGS=("onnxruntime==1.22.1" "tokenizers==0.21.4" "numpy==2.2.6")

command -v uv >/dev/null || { echo "needs uv (https://docs.astral.sh/uv/)" >&2; exit 1; }
mkdir -p "$MODEL_DIR"

if [ ! -x "$HOME_DIR/venv/bin/python" ]; then
  uv venv -q -p 3.12 "$HOME_DIR/venv"
fi
uv pip install -q -p "$HOME_DIR/venv/bin/python" "${PY_PKGS[@]}"

for f in onnx/model.onnx tokenizer.json; do
  name=$(basename "$f"); dest="$MODEL_DIR/$name"
  [ -s "$dest" ] || curl -sfL -o "$dest" "https://huggingface.co/$REPO/resolve/$REV/$f"
  # Re-checked on EVERY run, so a truncated or swapped file is never trusted.
  got=$(shasum -a 256 "$dest" | cut -d' ' -f1)
  want=$(expected_sha256 "$name")
  if [ -z "$want" ] || [ "$got" != "$want" ]; then
    echo "$name sha256 mismatch ($got) — refusing to use it" >&2
    mv "$dest" "$dest.rejected"
    exit 1
  fi
done
echo "$REV" > "$MODEL_DIR/REVISION"
echo "installed: $MODEL_DIR (rev ${REV:0:8}, model.onnx + tokenizer.json sha256 verified)"
echo "next: python3 scripts/recall.py --rebuild-vectors"
