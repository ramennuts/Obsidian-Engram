#!/usr/bin/env bash
# Engram installer — sets up the vault, the /handoff skill, and prints the hook
# snippet to add to ~/.claude/settings.json. Idempotent and safe to re-run.
#
#   ./install.sh [VAULT_PATH]      (default: ~/vault)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT="${1:-${ENGRAM_VAULT:-$HOME/vault}}"
MEMORY="${ENGRAM_MEMORY:-$HOME/memory}"
CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"

echo "Engram installer"
echo "  repo  : $REPO"
echo "  vault : $VAULT   (Layer 2 — working memory)"
echo "  memory: $MEMORY   (Layer 1 — durable memory)"
echo

# 1. Working-memory vault — seed from the template if it doesn't exist yet.
if [ -d "$VAULT" ]; then
  echo "✓ vault already exists at $VAULT (leaving it untouched)"
else
  cp -R "$REPO/vault-template" "$VAULT"
  echo "✓ created vault at $VAULT from vault-template/"
fi

# 2. Durable-memory dir — seed from the template if it doesn't exist yet.
if [ -d "$MEMORY" ]; then
  echo "✓ memory dir already exists at $MEMORY (leaving it untouched)"
else
  cp -R "$REPO/memory-template" "$MEMORY"
  echo "✓ created memory dir at $MEMORY from memory-template/"
fi

# 3. Skills.
mkdir -p "$SKILLS_DIR"
cp -R "$REPO/skills/handoff" "$REPO/skills/reflect" "$SKILLS_DIR/"
echo "✓ installed /handoff and /reflect skills -> $SKILLS_DIR/"

# 3. Tell the user how to finish (we don't edit settings.json for them).
cat <<EOF

Almost done — two manual steps:

1) Add the paths to your shell profile so the scripts find them:

   echo 'export ENGRAM_VAULT="$VAULT"'   >> ~/.zshrc   # or ~/.bashrc
   echo 'export ENGRAM_MEMORY="$MEMORY"' >> ~/.zshrc

2) Register the SessionStart hook: merge this into $CLAUDE_DIR/settings.json
   (keep any existing "hooks"):

   "hooks": {
     "SessionStart": [
       { "hooks": [
         { "type": "command",
           "command": "python3 $REPO/hooks/session-start.py" }
       ]}
     ]
   }

Then verify everything:

   ENGRAM_VAULT="$VAULT" ENGRAM_MEMORY="$MEMORY" python3 $REPO/scripts/doctor.py
   ENGRAM_MEMORY="$MEMORY" python3 $REPO/scripts/memory_lint.py

Optional — keep the queue lean by running the archiver weekly (cron example):

   0 7 * * 1  ENGRAM_VAULT="$VAULT" /usr/bin/python3 $REPO/scripts/archive_finished_queue.py --apply

Start a new Claude Code session and you should see the bootstrap appear. Type
/handoff at the end of a session to write the pickup brief for next time.
EOF
