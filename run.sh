#!/bin/zsh
# Restart the Jira digest web server in the background and open its page.
# http://127.0.0.1:8766/
cd "$(dirname "$0")"

# The JIRA_* variables are exported from ~/.zprofile, which only login shells
# read. Load it when this script runs from a non-login shell (Finder,
# Spotlight, a launcher), or the server exits on start.
if [[ -z "${JIRA_PROJECTS:-}" && -r ~/.zprofile ]]; then
    source ~/.zprofile
fi
if [[ -z "${JIRA_PROJECTS:-}" ]]; then
    echo "JIRA_PROJECTS is not set; see README.txt" >&2
    exit 1
fi

LOG=/tmp/jira-digest.log
pkill -f jira_digest_web.py
nohup ./jira_digest_web.sh --no-browser > "$LOG" 2>&1 &
# Give the server a moment to start listening before opening the page.
for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 0.3
    if curl -s -o /dev/null http://127.0.0.1:8766/; then
        open http://127.0.0.1:8766/
        exit 0
    fi
done
echo "Server did not start; log ($LOG):" >&2
cat "$LOG" >&2
exit 1
