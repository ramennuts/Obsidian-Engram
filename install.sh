#!/usr/bin/env bash
# Engram installer — sets up the vault, the /handoff skill, and prints the hook
# snippet to add to ~/.claude/settings.json. Idempotent and safe to re-run.
#
#   ./install.sh [VAULT_PATH]      (default: ~/vault)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT="${1:-${ENGRAM_VAULT:-$HOME/vault}}"
CLAUDE_DIR="$HOME/.claude"
SKILLS_DIR="$CLAUDE_DIR/skills"

echo "Engram installer"
echo "  repo : $REPO"
echo "  vault: $VAULT"
echo

# 1. Vault — seed from the template if it doesn't exist yet.
if [ -d "$VAULT" ]; then
  echo "✓ vault already exists at $VAULT (leaving it untouched)"
else
  cp -R "$REPO/vault-template" "$VAULT"
  echo "✓ created vault at $VAULT from vault-template/"
fi

# 2. /handoff skill.
mkdir -p "$SKILLS_DIR"
cp -R "$REPO/skills/handoff" "$SKILLS_DIR/"
echo "✓ installed /handoff skill -> $SKILLS_DIR/handoff"

# 3. Tell the user how to finish (we don't edit settings.json for them).
cat <<EOF

Almost done — two manual steps:

1) Add ENGRAM_VAULT to your shell profile so the scripts find your vault:

   echo 'export ENGRAM_VAULT="$VAULT"' >> ~/.zshrc   # or ~/.bashrc

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

   ENGRAM_VAULT="$VAULT" python3 $REPO/scripts/doctor.py

Optional — keep the queue lean by running the archiver weekly (cron example):

   0 7 * * 1  ENGRAM_VAULT="$VAULT" /usr/bin/python3 $REPO/scripts/archive_finished_queue.py --apply

Start a new Claude Code session and you should see the bootstrap appear. Type
/handoff at the end of a session to write the pickup brief for next time.
EOF
