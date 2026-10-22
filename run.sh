#!/bin/zsh
# http://127.0.0.1:8766/
pkill -f jira_digest_web.py
nohup ./jira_digest_web.sh --no-browser > /tmp/jira-digest.log 2>&1 &
