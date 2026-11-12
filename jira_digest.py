#!/usr/bin/env python3
"""Show the Jira tickets assigned to me, filtered and sorted.

With no options this lists the open (To Do, Open, In Progress, or In Review)
tickets assigned to me in the JIRA_PROJECTS that were created this year and
aren't labelled with one of the JIRA_NOT_LABELS, sorted by project and then
by severity, highest first. --parent narrows them to the children of an epic or other parent. See
parse_args() or README.txt for the options.

Environment (see README.txt):
  JIRA_URL              the Jira site, e.g. https://example.atlassian.net
  JIRA_EMAIL            the Atlassian account's email
  JIRA_TOKEN            Atlassian API token, from
                        https://id.atlassian.com/manage-profile/security/api-tokens
  JIRA_PROJECTS         project keys to scan, comma separated
  JIRA_SEVERITY_FIELDS  custom field ids holding a ticket's severity, comma
                        separated (optional)
  JIRA_NOT_LABELS       labels skipped by default, comma separated (optional)
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Settings

def env_list(name):
    """The comma-separated environment variable NAME as a list of strings."""
    return [s.strip() for s in os.environ.get(name, "").split(",") if s.strip()]


# The Jira site and the account the token belongs to.
JIRA = os.environ.get("JIRA_URL", "").rstrip("/")
BROWSE = JIRA + "/browse/"
EMAIL = os.environ.get("JIRA_EMAIL", "")

# Project keys to scan. The web page shows the project names it finds in the
# data next to these keys.
PROJECTS = env_list("JIRA_PROJECTS")

# A Jira site can have several custom fields named "Severity" (find their ids
# with GET /rest/api/3/field). A ticket's severity is the first of them that
# is set; with none configured the Severity column stays empty.
SEVERITY_FIELDS = env_list("JIRA_SEVERITY_FIELDS")
SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]  # highest first

# Jira's priorities, highest first, for sorting the Priority column.
PRIORITY_ORDER = [
    "Highest", "Blocker", "Critical", "High", "Major", "Medium", "Minor",
    "Low", "Lowest", "Trivial",
]

# Default filters: the statuses shown, and the labels skipped, unless
# --status or --not-labels says otherwise.
DEFAULT_STATUSES = "To Do,Open,In Progress,In Review"
DEFAULT_NOT_LABELS = os.environ.get("JIRA_NOT_LABELS", "")

# Columns that can be shown, in the order they appear, and the defaults.
COLUMNS = {
    "ticket": "Ticket",
    "title": "Title",
    "status": "Status",
    "severity": "Severity",
    "labels": "Labels",
    "parent": "Parent",
    "project": "Project",
    "type": "Type",
    "priority": "Priority",
    "assignee": "Assignee",
    "reporter": "Reporter",
    "created": "Created",
    "updated": "Updated",
    "fixversions": "Fix versions",
    "components": "Components",
    "resolution": "Resolution",
}
DEFAULT_COLUMNS = ["ticket", "title", "status", "priority", "severity", "labels"]
ALWAYS_COLUMN = "priority"  # shown whatever --columns says, before severity

# Column widths of the terminal table.
TEXT_WIDTHS = {
    "ticket": 10,
    "title": 56,
    "status": 12,
    "severity": 8,
    "labels": 30,
    "parent": 10,
    "project": 7,
    "type": 6,
    "priority": 8,
    "assignee": 8,
    "reporter": 18,
    "created": 10,
    "updated": 10,
    "fixversions": 14,
    "components": 14,
    "resolution": 11,
}

CACHE_FILE = Path.home() / ".cache" / "jira-digest" / "tickets.json"
CACHE_MAX_AGE = 4 * 3600
CACHE_VERSION = 2  # bump when FIELDS or simplify() change

# The people who can be assigned tickets in PROJECTS, for the web page's
# assignee list. They change rarely, so they are kept longer than tickets.
USERS_CACHE_FILE = CACHE_FILE.with_name("users.json")
USERS_MAX_AGE = 24 * 3600
USERS_PAGE_SIZE = 1000

PAGE_SIZE = 100
API_RETRIES = 3

# Terminals that turn OSC 8 escape sequences into clickable links.
OSC8_TERMINALS = {"iTerm.app", "ghostty", "WezTerm", "vscode"}

FIELDS = [
    "summary", "status", "labels", "project", "priority", "created", "updated",
    "issuetype", "assignee", "reporter", "fixVersions", "components",
    "resolution", "description", "comment", "parent",
] + SEVERITY_FIELDS

# Atlassian account ids: 24 hex digits, "557058:<uuid>", or "<uuid>".
ACCOUNT_ID = re.compile(r"^(?:[0-9a-f]{24}|\d+:[0-9a-f-]{36}|[0-9a-f-]{36})$", re.I)


# ---------------------------------------------------------------------------
# Jira API


def auth_header():
    """Return the Authorization header value, or exit if the environment is
    missing any of the required settings (see the module docstring)."""
    token = os.environ.get("JIRA_TOKEN", "")
    missing = [
        name for name, value in [
            ("JIRA_URL", JIRA), ("JIRA_EMAIL", EMAIL), ("JIRA_TOKEN", token),
            ("JIRA_PROJECTS", PROJECTS),
        ] if not value
    ]
    if missing:
        sys.exit(f"{', '.join(missing)} not set; see README.txt")
    return "Basic " + base64.b64encode(f"{EMAIL}:{token}".encode()).decode()


def jira_request(auth, path, body=None, params=None):
    """GET (or POST when body is given) a Jira REST path and return the JSON."""
    url = JIRA + path + ("?" + urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": auth, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(API_RETRIES):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code in (429, 502, 503, 504) and attempt < API_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            try:
                errors = json.loads(detail)
                detail = "; ".join(
                    errors.get("errorMessages", [])
                    + [f"{k}: {v}" for k, v in errors.get("errors", {}).items()]
                ) or detail
            except ValueError:
                pass
            if e.code == 401:
                detail = "check JIRA_TOKEN and JIRA_EMAIL. " + detail
            raise RuntimeError(f"Jira returned {e.code} for {path}: {detail[:500]}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < API_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Jira request failed for {path}: {e}")


def myself(auth):
    user = jira_request(auth, "/rest/api/3/myself")
    return {"id": user["accountId"], "name": user["displayName"]}


def resolve_assignees(auth, names, me):
    """Turn the names typed in the assignee filter into account ids.

    "me" (or nothing) is the token owner, "unassigned" matches tickets with
    no assignee, an account id is used as is, and anything else is looked up
    as a display name or email; an exact match wins, else the first hit.
    """
    out = []
    for name in names or ["me"]:
        low = name.lower()
        if low in ("", "me"):
            who = me
        elif low == "unassigned":
            who = {"id": None, "name": "unassigned"}
        elif ACCOUNT_ID.match(name):
            user = jira_request(auth, "/rest/api/3/user", params={"accountId": name})
            who = {"id": user["accountId"], "name": user["displayName"]}
        else:
            users = jira_request(
                auth, "/rest/api/3/user/search", params={"query": name, "maxResults": 20}
            )
            users = [
                u for u in users
                if u.get("accountType", "atlassian") == "atlassian" and u.get("active", True)
            ]
            if not users:
                raise RuntimeError(f"no Jira user matches {name!r}")
            exact = [
                u for u in users
                if u["displayName"].lower() == low
                or (u.get("emailAddress") or "").lower() == low
            ]
            user = (exact or users)[0]
            who = {"id": user["accountId"], "name": user["displayName"]}
        if who not in out:
            out.append(who)
    return out


def fetch_users(auth):
    """Return the active people who can be assigned tickets in any of
    PROJECTS, as {"id", "name"} sorted by name."""
    def project_users(project):
        found, start = [], 0
        while True:
            page = jira_request(
                auth, "/rest/api/3/user/assignable/search",
                params={"project": project, "startAt": start, "maxResults": USERS_PAGE_SIZE},
            )
            if not page:
                return found
            found += page
            start += USERS_PAGE_SIZE

    # A project open to the whole site has thousands of people and takes a
    # few seconds, so the projects are asked at the same time.
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(project_users, PROJECTS))
    names = {}
    for u in (u for page in pages for u in page):
        if u.get("accountType", "atlassian") == "atlassian" and u.get("active", True):
            names[u["accountId"]] = u.get("displayName") or u["accountId"]
    return sorted(
        ({"id": i, "name": n} for i, n in names.items()),
        key=lambda u: u["name"].lower(),
    )


def load_users(auth):
    """Return fetch_users(), from its cache when that is fresh and was made
    for the same PROJECTS."""
    if USERS_CACHE_FILE.exists():
        age = time.time() - USERS_CACHE_FILE.stat().st_mtime
        cached = json.loads(USERS_CACHE_FILE.read_text())
        if age < USERS_MAX_AGE and cached.get("projects") == PROJECTS:
            return cached["users"]
    users = fetch_users(auth)
    USERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_CACHE_FILE.write_text(json.dumps({"projects": PROJECTS, "users": users}))
    return users


def fetch_tickets(auth, assignees, since):
    """Return the tickets in PROJECTS assigned to assignees (resolve_assignees()
    output), created on or after since (YYYY-MM-DD, or None for all time)."""
    ids = [a["id"] for a in assignees if a["id"]]
    clauses = []
    if ids:
        clauses.append("assignee in (" + ", ".join(f'"{i}"' for i in ids) + ")")
    if any(a["id"] is None for a in assignees):
        clauses.append("assignee is EMPTY")
    jql = f"project in ({', '.join(PROJECTS)}) and ({' or '.join(clauses)})"
    if since:
        jql += f' and created >= "{since}"'
    jql += " ORDER BY created DESC"
    tickets, token = [], None
    while True:
        body = {
            "jql": jql,
            "maxResults": PAGE_SIZE,
            "fields": FIELDS,
            "expand": "renderedFields",
        }
        if token:
            body["nextPageToken"] = token
        page = jira_request(auth, "/rest/api/3/search/jql", body)
        tickets += [simplify(issue) for issue in page.get("issues", [])]
        token = page.get("nextPageToken")
        if page.get("isLast", True) or not token:
            return tickets


def simplify(issue):
    """Reduce a Jira issue to the fields the reports use."""
    f = issue["fields"]
    r = issue.get("renderedFields") or {}
    name = lambda x: (x or {}).get("name") or ""
    user = lambda x: (x or {}).get("displayName") or ""
    severity = next((f[s]["value"] for s in SEVERITY_FIELDS if f.get(s)), "")
    raw = f.get("comment") or {}
    rendered = {c.get("id"): c for c in (r.get("comment") or {}).get("comments", [])}
    comments = [
        {
            "author": user(c.get("author")),
            "created": c["created"][:10],
            "body": rendered.get(c.get("id"), {}).get("body", ""),
        }
        for c in raw.get("comments", [])
    ]
    parent = f.get("parent") or {}
    return {
        "key": issue["key"],
        "url": BROWSE + issue["key"],
        "summary": f.get("summary") or "",
        "parent": parent.get("key") or "",
        "parent_summary": (parent.get("fields") or {}).get("summary") or "",
        "status": name(f.get("status")),
        "severity": severity,
        "labels": list(f.get("labels") or []),
        "project": f["project"]["key"],
        "project_name": f["project"]["name"],
        "type": name(f.get("issuetype")),
        "priority": name(f.get("priority")),
        "assignee": user(f.get("assignee")),
        "reporter": user(f.get("reporter")),
        "created": f["created"][:10],
        "updated": f["updated"][:10],
        "fixversions": [v["name"] for v in f.get("fixVersions") or []],
        "components": [c["name"] for c in f.get("components") or []],
        "resolution": name(f.get("resolution")),
        "description": r.get("description") or "",
        "comments": comments,
        "comment_total": raw.get("total", len(comments)),
    }


# ---------------------------------------------------------------------------
# Cache


def start_of_year():
    return date.today().replace(month=1, day=1).isoformat()


def read_cache():
    if not CACHE_FILE.exists():
        return None
    data = json.loads(CACHE_FILE.read_text())
    return data if data.get("version") == CACHE_VERSION else None


def load_data(auth, force, assignee_names, since):
    """Return the tickets of the given assignees created on or after since,
    from the cache when it holds them and is fresh.

    The cache holds one fetch: the tickets of one set of assignees in one set
    of projects from one start date. Asking for other assignees, other
    projects (JIRA_PROJECTS changed), or an earlier date, refetches.
    Fetches start no later than January 1 of this year so that the default
    "created after" filter never needs another fetch.
    """
    query = [n.strip().lower() for n in assignee_names if n.strip()] or ["me"]
    data = read_cache()
    if data:
        age = time.time() - CACHE_FILE.stat().st_mtime
        covers = data["since"] is None or (since is not None and data["since"] <= since)
        if (not force and age < CACHE_MAX_AGE and covers
                and data["query"] == query
                and data.get("projects") == PROJECTS):
            print(f"(cached {int(age // 60)} min ago; --force to refresh)",
                  file=sys.stderr)
            return data
    me = data["me"] if data else myself(auth)
    if data and data["query"] == query:
        assignees = data["assignees"]
    else:
        assignees = resolve_assignees(auth, query, me)
    fetch_since = None if since is None else min(since, start_of_year())
    data = {
        "version": CACHE_VERSION,
        "me": me,
        "query": query,
        "projects": PROJECTS,
        "assignees": assignees,
        "since": fetch_since,
        "tickets": fetch_tickets(auth, assignees, fetch_since),
    }
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data))
    return data


# ---------------------------------------------------------------------------
# Filtering and sorting


def parse_list(text):
    return {m.strip().lower() for m in text.split(",") if m.strip()}


def parse_names(text):
    return [m.strip() for m in text.split(",") if m.strip()]


def parse_date(text):
    if text.lower() == "all":
        return None
    for fmt in ("%m-%d-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(
        f"expected m-d-yy, e.g. 10-5-26, or all: {text!r}"
    )


def parse_columns(text):
    columns = [c.strip().lower() for c in text.split(",") if c.strip()]
    bad = [c for c in columns if c not in COLUMNS]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown column(s) {', '.join(bad)}; choose from {', '.join(COLUMNS)}"
        )
    return with_always_column(columns or DEFAULT_COLUMNS)


def with_always_column(columns):
    """columns with ALWAYS_COLUMN in it: where it is if that is before
    severity, else just before severity, after status, or at the end."""
    columns = list(columns)
    if ALWAYS_COLUMN in columns and (
        "severity" not in columns
        or columns.index(ALWAYS_COLUMN) < columns.index("severity")
    ):
        return columns
    columns = [c for c in columns if c != ALWAYS_COLUMN]
    for anchor, offset in (("severity", 0), ("status", 1)):
        if anchor in columns:
            at = columns.index(anchor) + offset
            return columns[:at] + [ALWAYS_COLUMN] + columns[at:]
    return columns + [ALWAYS_COLUMN]


def rank(value, order):
    """The position of value in order (a list, highest first) ignoring case;
    unknown values go after the known ones and an empty value last."""
    if not value:
        return len(order) + 1
    lower = [s.lower() for s in order]
    return lower.index(value.lower()) if value.lower() in lower else len(order)


def severity_rank(severity):
    """Smaller is more severe."""
    return rank(severity, SEVERITY_ORDER)


def priority_rank(priority):
    """Smaller is a higher priority."""
    return rank(priority, PRIORITY_ORDER)


def select_rows(data, args):
    """Return (title, tickets) for the filters in args: project, status,
    priority, severity, parent (sets, lower case, empty for all; priority,
    severity, and parent may hold "none"), created (YYYY-MM-DD or None),
    labels and not_labels (sets, lower case). When both priority and
    severity are set a ticket needs to match either one, not both; the
    other filters all have to match.
    A label filter matches a ticket label that contains it, so "oracle"
    matches "Price_Oracle"."""

    def has_label(ticket, wanted):
        labels = [label.lower() for label in ticket["labels"]]
        return any(w in label for w in wanted for label in labels)

    rows = []
    for t in data["tickets"]:
        if args.project and t["project"].lower() not in args.project:
            continue
        if args.status and t["status"].lower() not in args.status:
            continue
        if args.priority or args.severity:
            priority_ok = (t["priority"].lower() or "none") in args.priority
            severity_ok = (t["severity"].lower() or "none") in args.severity
            if not (priority_ok or severity_ok):
                continue
        if args.parent and (t["parent"].lower() or "none") not in args.parent:
            continue
        if args.created and t["created"] < args.created:
            continue
        if args.labels and not has_label(t, args.labels):
            continue
        if args.not_labels and has_label(t, args.not_labels):
            continue
        rows.append(t)
    # Newest first within a project and severity; sorts are stable.
    rows.sort(key=lambda t: t["created"], reverse=True)
    rows.sort(key=lambda t: (t["project"], severity_rank(t["severity"])))
    names = ", ".join(a["name"] for a in data["assignees"])
    return f"Tickets assigned to {names} ({len(rows)})", rows


# ---------------------------------------------------------------------------
# Output


def initials(name):
    """The first letter of each word of a person's name: "Jane van Doe" gives
    "JVD". Words that don't start with a letter or digit are skipped."""
    return "".join(w[0].upper() for w in name.split() if w[0].isalnum())


def cell_text(row, column):
    """The plain text of one table cell."""
    if column == "assignee":
        return initials(row["assignee"]) or "-"
    value = row[{"ticket": "key", "title": "summary"}.get(column, column)]
    if isinstance(value, list):
        value = ", ".join(value)
    return value or "-"


def clip(text, width):
    return text if len(text) <= width else text[: width - 1] + "…"


def link_style():
    """"osc8" to make ticket keys clickable links, else "url" to print the
    URL on its own line."""
    if not sys.stdout.isatty():
        return "url"
    if os.environ.get("TERM_PROGRAM") in OSC8_TERMINALS:
        return "osc8"
    if os.environ.get("TERM") == "xterm-kitty":
        return "osc8"
    return "url"


def terminal_link(url, text):
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def text_line(cells, columns):
    widths = [TEXT_WIDTHS[c] for c in columns]
    padded = [clip(c, w).ljust(w) for c, w in zip(cells, widths)]
    return "  ".join(padded).rstrip()


def text_report(title, rows, columns, links=None):
    rule = "=" * (sum(TEXT_WIDTHS[c] for c in columns) + (2 * (len(columns) - 1)))
    out = [title, text_line([COLUMNS[c] for c in columns], columns), rule]
    for row in rows:
        line = text_line([cell_text(row, c) for c in columns], columns)
        if links == "osc8" and "ticket" in columns:
            # Wrap after padding so the escape codes don't shift the columns.
            start = line.index(row["key"])
            end = start + len(row["key"])
            line = line[:start] + terminal_link(row["url"], row["key"]) + line[end:]
        out.append(line)
        if links == "url":
            out.append(row["url"])
    if not rows:
        out.append("No tickets match these filters.")
    return "\n".join(out)


def md_escape(text):
    return text.replace("|", "\\|")


def markdown_report(title, rows, columns):
    out = [
        f"**{title}**",
        "",
        "| " + " | ".join(COLUMNS[c] for c in columns) + " |",
        "|" + "---|" * len(columns),
    ]
    for row in rows:
        cells = []
        for c in columns:
            text = md_escape(cell_text(row, c))
            cells.append(f"[{text}]({row['url']})" if c == "ticket" else text)
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Command line


def parse_args():
    parser = argparse.ArgumentParser(description="Show the Jira tickets assigned to me.")
    parser.add_argument(
        "--assignee",
        type=parse_names,
        default=["me"],
        metavar="A,B",
        help="names, emails, or account ids; also me and unassigned (default: me)",
    )
    parser.add_argument(
        "--project",
        type=parse_list,
        default=set(),
        metavar="A,B",
        help=f"project keys to include (default: all of JIRA_PROJECTS: {', '.join(PROJECTS) or 'unset'})",
    )
    parser.add_argument(
        "--status",
        type=parse_list,
        default=parse_list(DEFAULT_STATUSES),
        metavar="A,B",
        help=f'statuses to include, or all (default: "{DEFAULT_STATUSES}")',
    )
    parser.add_argument(
        "--priority",
        type=parse_list,
        default=set(),
        metavar="A,B",
        help="priorities to include; none for tickets without one; with --severity, "
             "either may match (default: all)",
    )
    parser.add_argument(
        "--severity",
        type=parse_list,
        default=set(),
        metavar="A,B",
        help="severities to include; none for tickets without one (default: all)",
    )
    parser.add_argument(
        "--parent",
        type=parse_list,
        default=set(),
        metavar="A,B",
        help="only tickets under these parent keys, e.g. PROJ-136; none for tickets without a parent (default: all)",
    )
    parser.add_argument(
        "--created",
        type=parse_date,
        default=start_of_year(),
        metavar="m-d-yy",
        help="only tickets created on or after this date, or all (default: Jan 1)",
    )
    parser.add_argument(
        "--labels",
        type=parse_list,
        default=set(),
        metavar="A,B",
        help="only tickets with a label containing one of these (oracle matches Price_Oracle)",
    )
    parser.add_argument(
        "--not-labels",
        type=parse_list,
        default=parse_list(DEFAULT_NOT_LABELS),
        metavar="A,B",
        help=f"skip tickets with a label containing one of these, or none (default: {DEFAULT_NOT_LABELS or 'none'})",
    )
    parser.add_argument(
        "--columns",
        type=parse_columns,
        default=DEFAULT_COLUMNS,
        metavar="A,B",
        help=f"columns to show, in this order, from {', '.join(COLUMNS)}; "
             f"{ALWAYS_COLUMN} is always shown (default: {','.join(DEFAULT_COLUMNS)})",
    )
    parser.add_argument("--markdown", action="store_true", help="print Markdown")
    parser.add_argument(
        "--force", action="store_true", help="fetch from Jira even if cached"
    )
    args = parser.parse_args()
    # "all" and "none" switch the defaults off.
    if args.status == {"all"}:
        args.status = set()
    if args.not_labels == {"none"}:
        args.not_labels = set()
    return args


def main():
    args = parse_args()
    auth = auth_header()
    try:
        data = load_data(auth, args.force, args.assignee, args.created)
    except RuntimeError as e:
        sys.exit(str(e))
    title, rows = select_rows(data, args)
    if args.markdown:
        print(markdown_report(title, rows, args.columns))
    else:
        print(text_report(title, rows, args.columns, link_style()))


if __name__ == "__main__":
    main()
