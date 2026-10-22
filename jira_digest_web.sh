#!/usr/bin/env bash
# Serve the Jira digest as a web page and open it. Arguments are passed to
# jira_digest_web.py, e.g.
#   ./jira_digest_web.sh --port 9000
set -euo pipefail

if [[ -z "${JIRA_TOKEN:-}" ]]; then
    # Fall back to a token stored with
    #   security add-generic-password -a "$USER" -s jira-digest -w '<token>'
    JIRA_TOKEN="$(security find-generic-password -s jira-digest -w 2>/dev/null || true)"
    export JIRA_TOKEN
fi

exec python3 "$(dirname "$0")/jira_digest_web.py" "$@"
