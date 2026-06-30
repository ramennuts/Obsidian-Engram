# Engram demo — regenerate from the repo root with:  vhs docs/demo.tape
# Records against a throwaway HOME so paths show as ~/… and every check is green.
# Setup it expects (a disposable demo home):
#   DEMO=/private/tmp/engram-demo-gif
#   mkdir -p "$DEMO/.claude/skills"
#   cp -R vault-template "$DEMO/vault"; cp -R memory-template "$DEMO/memory"
#   cp -R skills/handoff skills/reflect "$DEMO/.claude/skills/"
#   echo '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"python3 ~/engram/hooks/session-start.py"}]}]}}' > "$DEMO/.claude/settings.json"
Output docs/demo.gif

Require python3
Require jq

Set Shell zsh
Set FontSize 15
Set Width 1180
Set Height 720
Set Padding 24
Set Margin 18
Set MarginFill "#312e81"
Set BorderRadius 10
Set Theme "Catppuccin Mocha"
Set TypingSpeed 28ms

Hide
Type "setopt interactive_comments; export HOME=/private/tmp/engram-demo-gif; export ENGRAM_VAULT=$HOME/vault ENGRAM_MEMORY=$HOME/memory; export PROMPT='%F{212}engram%f %F{245}> %f'; clear"
Enter
Show

Sleep 700ms
Type "# 1 . is everything wired?"
Sleep 400ms
Enter
Type "python3 scripts/doctor.py"
Enter
Sleep 2.8s

Hide
Type "clear"
Enter
Show
Sleep 300ms
Type "# 2 . a lean bootstrap auto-injects at the start of EVERY session:"
Sleep 400ms
Enter
Type "python3 hooks/session-start.py | jq -r '.hookSpecificOutput.additionalContext' | head -17"
Enter
Sleep 3.2s

Hide
Type "clear"
Enter
Show
Sleep 300ms
Type "# 3 . finished items archive themselves; live ones never do:"
Sleep 400ms
Enter
Type "python3 scripts/archive_finished_queue.py"
Enter
Sleep 3.6s

Sleep 800ms
