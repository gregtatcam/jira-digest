Jira digest
===========

Shows the Jira tickets assigned to you (or to anyone) in a set of projects,
filtered by project, status, priority, severity, parent, creation date, and
labels, sorted by project and then by severity, highest first. By default it
shows what the board query

  status in ("To Do", Open, "In Progress", "In Review") and project in (...)
  and (labels not in (...) or labels is EMPTY)
  and assignee = me and created > startOfYear()
  ORDER BY project, severity desc

shows, so with no options you get your open tickets from this year.

Two front ends share the same code:

  jira_digest.sh       prints the table in the terminal
  jira_digest_web.sh   serves the table as a local web page with filter
                       controls and a popup for each ticket

Files
-----

  jira_digest.py        the tool: fetching, filtering, and the text/Markdown output
  jira_digest.sh        wrapper that finds JIRA_TOKEN and runs jira_digest.py
  jira_digest_web.py    local web server around jira_digest.py
  jira_digest_web.sh    wrapper that finds JIRA_TOKEN and runs jira_digest_web.py

Keep the four files in one directory; the web server imports jira_digest.py
from its own directory.

Requirements
------------

  - Python 3.9 or later. Only the standard library is used.
  - An Atlassian API token for your Jira account, created at
    https://id.atlassian.com/manage-profile/security/api-tokens
    (a plain token, not one "with scopes").

Configuration
-------------

Everything site-specific comes from the environment, e.g. in ~/.zprofile:

  export JIRA_URL='https://example.atlassian.net'   # your Jira site
  export JIRA_EMAIL='you@example.com'               # the token's account
  export JIRA_TOKEN='...'                           # the API token
  export JIRA_PROJECTS='PROJ,OTHER'                 # project keys to scan

Optional:

  export JIRA_SEVERITY_FIELDS='customfield_12345,customfield_23456'
  export JIRA_NOT_LABELS='FalsePositive'
  export JIRA_REVIEW_DIR="$HOME/reviews"

JIRA_REVIEW_DIR is the directory the web page's "review" link starts Claude
Code in. The default is Documents/Reports-CodeReview next to this project's
directory.

  export JIRA_DOCS_DIR="$HOME/reviews"

JIRA_DOCS_DIR is the directory your documents on tickets are kept in, at
any depth: a ticket's is a Markdown file with the key in its name, with or
without the hyphen (PROJ123-analysis.md), or in a directory named so.
Directories named "cache" are skipped. The default is Documents next to
this project's directory.

JIRA_SEVERITY_FIELDS lists the custom field ids that hold a ticket's
severity, when your site has such a field (Jira sites often have several
fields named "Severity"; list the ones your projects use, and the first one
set on a ticket wins). Find the ids with

  curl -s -u "$JIRA_EMAIL:$JIRA_TOKEN" "$JIRA_URL/rest/api/3/field" \
    | python3 -c 'import json,sys; [print(f["id"], f["name"]) for f in json.load(sys.stdin)]' \
    | grep -i severity

Without it the Severity column and filter stay empty. JIRA_NOT_LABELS lists
labels whose tickets are skipped by default, as --not-labels does; without it
nothing is skipped.

Instead of the environment, the token can live in the macOS keychain, which
the wrappers read when JIRA_TOKEN is unset:

  security add-generic-password -a "$USER" -s jira-digest -w '...'

Running in the terminal
-----------------------

  ./jira_digest.sh [options]

Options:

  --assignee A,B      Whose tickets: display names, emails, or account ids,
                      plus "me" and "unassigned". Default: me.
  --project A,B       Only these project keys. Default: all of JIRA_PROJECTS.
  --status A,B        Only these statuses, or "all".
                      Default: "To Do,Open,In Progress,In Review".
  --priority A,B      Only these priorities (Critical, High, Major, Medium,
                      Minor, Low, ...); "none" means tickets without one.
                      Default: all.
  --severity A,B      Only these severities (Critical, High, Medium, Low);
                      "none" means tickets without one. Default: all.
                      When both --priority and --severity are given a
                      ticket is shown if either matches; every other
                      filter has to match as well.
  --parent A,B        Only tickets under these parents (epics etc.), by
                      key, e.g. PROJ-136; "none" means tickets without a
                      parent. Default: all.
  --created m-d-yy    Only tickets created on or after this date, or "all".
                      Default: January 1 of this year.
  --labels A,B        Only tickets with a label that contains one of these,
                      so "oracle" matches Price_Oracle.
  --not-labels A,B    Skip tickets with a label that contains one of these,
                      or "none". Default: JIRA_NOT_LABELS, if set.
  --labels-mode M     How the --labels list combines: "or" shows a ticket
                      with any of the labels, "and" only a ticket with all
                      of them. Default: or.
  --not-labels-mode M How the --not-labels list combines: "and" skips a
                      ticket with any of the labels (not A and not B), "or"
                      skips only a ticket with all of them (not A or not
                      B). Default: and.
  --columns A,B       Columns to show, in this order, from: ticket, title,
                      status, severity, labels, parent, project, type,
                      priority, assignee, reporter, created, updated,
                      fixversions, components, resolution. "assignee"
                      shows the assignee's initials: "Jane Doe" is "JD".
                      Default: ticket,title,status,priority,severity,labels.
                      Priority is always shown: if it's left out, or put
                      after severity, it goes just before severity.
  --markdown          Print a Markdown table instead of the text table.
  --force             Fetch from Jira even if the cached data is under
                      4 hours old (see "Caching" below).

Names, statuses, priorities, severities, parents, and labels are matched
ignoring case. Labels
match as substrings, so --labels oracle finds Price_Oracle.

Examples:

  ./jira_digest.sh                                   my open tickets this year
  ./jira_digest.sh --severity high,medium            the ones that matter most
  ./jira_digest.sh --project PROJ --labels amm       my open PROJ tickets labelled AMM
  ./jira_digest.sh --parent PROJ-136                 the children of the PROJ-136 epic
  ./jira_digest.sh --status all --created all        everything ever assigned to me
  ./jira_digest.sh --assignee "Jane Doe" --status "In Review"
  ./jira_digest.sh --columns ticket,title,priority,updated --markdown

In iTerm2, Ghostty, WezTerm, kitty, and the VS Code terminal the ticket key
is a clickable link; in other terminals the URL is printed under each row.

Running the web page
--------------------

  ./jira_digest_web.sh [--port N] [--no-browser]

This starts a server on http://127.0.0.1:8766/ (change with --port) and
opens it in your browser. Only your own machine can connect. Stop it with
Ctrl-C.

The page has the same filters as the options above: assignee, project,
status, priority, severity, parent, and column check boxes, the created-after date,
and the "labels in" and "labels not in" text fields, each with an or/and
choice for how its list combines (see --labels-mode and --not-labels-mode).
With boxes ticked in
both the Priority and Severity groups a ticket is shown if either matches,
while every other filter must match too. The parent boxes list
the parents (epics and so on) of the fetched tickets, with "(none)" for
tickets that have no parent. Check boxes and the date apply
immediately; after typing in a text field press "Apply filters". A group
with nothing checked means everything, so unchecking both default statuses
shows tickets in every status. "Defaults" goes back to the default filters.
"Fetch from Jira" refetches regardless of the cache.

The Assignee dropdown lists "Me", "Unassigned", and everyone who can be
assigned tickets in the JIRA_PROJECTS. Type in its search box to narrow the
list, tick one or more people, and close the list (click outside it or
press Escape) to apply. The list of people is fetched from Jira once a day
(it takes a few seconds) and kept in ~/.cache/jira-digest/users.json;
delete that file to refetch it sooner.

Clicking the Ticket, Status, Severity, or Priority header sorts the table
by that column, descending first and ascending on the next click; an arrow in the
header shows the direction. Reloading the page restores the default order
(project, then severity, then newest first).

Dragging a column header onto another header moves the column there. The
column check boxes follow the shown order, so the new order stays in the
page's URL like the other filters until "Defaults" is clicked. The Priority
column is always shown and stays before Severity; its box can't be
unticked.

The Assignee column shows the assignee's initials (hover over them for the
full name). It is off by default.

Clicking a ticket key or title opens the ticket in Jira in a separate
browser window, where you can edit it, change its status, or comment as
usual. Every ticket opens in that same window, so it doesn't pile up tabs.
A middle or Cmd click opens a normal tab instead. (Jira doesn't allow its
pages to be embedded in other pages, so an editable in-page popup isn't
possible.)

The small (i) icon next to the key shows a read-only preview in the page,
from the cached data: the ticket's fields, description, and comments.
Close it with the Close button, Escape, or a click outside it.

"review" next to the key starts a review of the ticket with Claude Code:
it takes a Terminal tab (macOS only) that is idle, that is, a shell at its
prompt with nothing running in it (so not one with a Claude Code session),
or opens a new Terminal window when no tab is idle, brings it to the front,
goes to JIRA_REVIEW_DIR, and
runs claude with the prompt "Review Jira ticket PROJ-123", which also asks
it to resume from a document on the ticket that is already there (one with
PROJ123 or PROJ-123 in its name) rather than start over. The first time,
macOS may ask to let the server control Terminal. "review" is greyed out
for a ticket that a running Claude Code session was started on this way
(the ticket key is in the session's command line), so that a ticket isn't
reviewed twice at once; reload the page after closing the session. A
session that was started without the key and took up the ticket later
isn't noticed. For a ticket with such a session, "session" takes the place
of "review"; click it to bring the session's Terminal window to the front.

"review" reads "resume" for a ticket you have a document on, and "notes"
with a date under the key opens that document (the newest when there are
several, and the date it was last changed); see JIRA_DOCS_DIR above. Next
to it are the ticket's open PRs, each a link to the PR on GitHub: the PRs
that name the ticket in their title or branch, or link to it in their
description. They come from the PRs that pr-review-digest, a sibling
project, has fetched and saved (~/.cache/pr-review-digest/prs.json), so
they are as fresh as its last fetch, and absent without it.

None of this uses Claude: only the preview's summary does, once per ticket.

The preview starts with a summary: a few sentences on what the ticket is
about, written by the claude command (Claude Code,
https://claude.com/claude-code), which must be installed and logged in. The
ticket's title and description are sent to Claude for this. A summary is
written once, the first time a ticket's preview opens (it takes a few
seconds), and saved in ~/.cache/jira-digest/summaries.json; it isn't
rewritten when the ticket changes, so delete the ticket's entry there (or
the file) to have it written again. Without the claude command the preview
says so and shows the rest as before.

The saved summaries are shared with pr-review-digest
(https://github.com/gregtatcam/pr-review-digest), which shows them next to
a PR's tickets; either one writes a summary the other then reuses.
ticket_summary.py is the same file in both projects.

After changing a ticket in Jira, press "Fetch from Jira" to see the change
in the table; the cache doesn't notice edits on its own.

Caching
-------

The fetched tickets are saved in ~/.cache/jira-digest/tickets.json and
reused for 4 hours, so changing filters is instant. The cache holds one
fetch: the tickets of one assignee list from one start date (never later
than January 1 of this year). Choosing a different assignee, or a
created-after date before the cached start, refetches automatically.
Fetching usually takes a few seconds.

Customizing
-----------

The site, account, projects, severity fields, and skipped labels come from
the environment (see "Configuration"). Constants near the top of
jira_digest.py control the rest:

  SEVERITY_ORDER       the sort order of severities, highest first
  PRIORITY_ORDER       the sort order of priorities, highest first
  DEFAULT_STATUSES     the default status filter
  COLUMNS,             the available and default columns
  DEFAULT_COLUMNS
  CACHE_MAX_AGE        how long fetched data is reused
