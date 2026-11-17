#!/usr/bin/env python3
"""Serve the jira_digest.py report as a local web page with its filters.

Options:
  --port N      Port to listen on (default 8766). Only localhost can connect.
  --no-browser  Don't open the page in the browser on start.

The filters work like the jira_digest.py options of the same names. Clicking
a ticket key or title opens the ticket in Jira in a separate browser window
where it can be edited; the icon next to the key shows a read-only preview
in the page. "Fetch from Jira" refetches even if the cache is under 4 hours
old.

Environment: the same variables as jira_digest.py (JIRA_URL, JIRA_EMAIL,
JIRA_TOKEN, JIRA_PROJECTS, and the optional JIRA_SEVERITY_FIELDS and
JIRA_NOT_LABELS); see README.txt.
"""

import argparse
import json
import re
import sys
import threading
import time
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import jira_digest as digest
import ticket_summary

SCRIPT_TAG = re.compile(r"<script\b.*?</script>", re.DOTALL | re.IGNORECASE)
RELATIVE_URL = re.compile(r'\b(href|src)="/')

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{ font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 20px; color: #1f2328; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .meta {{ color: #59636e; margin-bottom: 12px; }}
  .failure {{ background: #ffebe9; border: 1px solid #ff8182; padding: 8px;
              margin-bottom: 12px; white-space: pre-wrap; }}
  form {{ display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: flex-start;
          background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px;
          padding: 12px; margin-bottom: 12px; }}
  fieldset {{ border: none; padding: 0; margin: 0; }}
  .label {{ font-weight: 600; display: block; margin-bottom: 4px; }}
  input[type=text] {{ width: 180px; }}
  .boxes {{ max-height: 130px; overflow-y: auto; }}
  .boxes label {{ display: block; white-space: nowrap; }}
  .boxes label[hidden] {{ display: none; }}
  /* Assignee dropdown */
  .pick {{ position: relative; }}
  .pick summary {{ cursor: pointer; background: #fff; border: 1px solid #d1d9e0;
                   border-radius: 4px; padding: 2px 8px; width: 180px;
                   overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .pick .panel {{ position: absolute; z-index: 50; top: 100%; left: 0;
                  background: #fff; border: 1px solid #d1d9e0; border-radius: 6px;
                  padding: 8px; min-width: 260px;
                  box-shadow: 0 8px 24px rgba(0,0,0,0.2); }}
  .pick .boxes {{ max-height: 280px; }}
  .pick input[type=search] {{ width: 100%; box-sizing: border-box; margin-bottom: 6px; }}
  .buttons {{ align-self: flex-end; display: flex; gap: 8px; }}
  button {{ padding: 4px 12px; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #d1d9e0; padding: 6px 8px; vertical-align: top;
            text-align: left; }}
  th {{ background: #f6f8fa; position: sticky; top: 0; }}
  th[draggable] {{ cursor: grab; }}
  th.sortable {{ cursor: pointer; user-select: none; white-space: nowrap; }}
  th.over {{ border-left: 3px solid #0969da; }}
  th.sortable:hover {{ background: #eaeef2; }}
  th .arrow {{ display: inline-block; width: 1em; color: #59636e; }}
  .nowrap {{ white-space: nowrap; }}
  a.key {{ font-weight: 600; }}
  a.jira {{ margin-left: 4px; text-decoration: none; font-size: 12px; }}
  a.title {{ color: inherit; text-decoration: none; }}
  a.title:hover {{ text-decoration: underline dotted; }}
  .chip {{ display: inline-block; background: #eaeef2; border-radius: 10px;
           padding: 0 7px; margin: 1px 2px 1px 0; font-size: 12px;
           white-space: nowrap; }}
  .sev-critical, .sev-high {{ color: #cf222e; font-weight: 600; }}
  .sev-medium {{ color: #bc4c00; font-weight: 600; }}
  .sev-low {{ color: #59636e; }}
  /* Ticket popup */
  #modal {{ position: fixed; inset: 0; background: rgba(31, 35, 40, 0.45);
            display: flex; align-items: center; justify-content: center;
            z-index: 100; }}
  #modal[hidden] {{ display: none; }}
  #modal-box {{ background: #fff; border-radius: 8px; width: 860px;
                max-width: 92vw; max-height: 88vh; display: flex;
                flex-direction: column; box-shadow: 0 16px 48px rgba(0,0,0,0.3); }}
  #modal-close {{ align-self: flex-end; margin: 6px 8px 0 0; }}
  #modal-content {{ overflow-y: auto; padding: 0 20px 20px; }}
  .ticket h2 {{ font-size: 17px; margin: 0 0 8px; }}
  .ticket dl {{ display: grid; grid-template-columns: max-content 1fr;
                gap: 2px 12px; margin: 0 0 12px; font-size: 13px; }}
  .ticket dt {{ color: #59636e; }}
  .ticket dd {{ margin: 0; }}
  .ticket h3 {{ font-size: 14px; margin: 14px 0 6px; border-bottom: 1px solid #d1d9e0; }}
  .ticket .body {{ font-size: 13px; line-height: 1.45; }}
  .ticket .body pre, .ticket .body .code {{ background: #f6f8fa; padding: 8px;
         overflow-x: auto; font-size: 12px; }}
  .ticket .body tt, .ticket .body code {{ font-family: ui-monospace, Menlo, monospace;
         font-size: 12px; }}
  .ticket .body img {{ max-width: 100%; }}
  .ticket .body table {{ width: auto; }}
  .ticket .empty {{ color: #59636e; font-style: italic; }}
  .ticket .summary {{ white-space: pre-wrap; }}
  .comment {{ border-top: 1px solid #eaeef2; padding: 6px 0; }}
  .comment .who {{ color: #59636e; font-size: 12px; margin-bottom: 2px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">{cache}</div>
{error}
<form method="get" id="filters">
  <input type="hidden" name="f" value="1">
  <fieldset>
    <span class="label">Assignee</span>
    <details class="pick" id="who">
      <summary title="Pick whose tickets to show; closing the list applies the change">{assignee}</summary>
      <div class="panel">
        <input type="search" id="who-search" placeholder="Find a person"
               autocomplete="off" data-lpignore="true" data-1p-ignore>
        <div class="boxes">{assignees}</div>
      </div>
    </details>
  </fieldset>
  <fieldset>
    <span class="label">Project</span>
    <div class="boxes">{projects}</div>
  </fieldset>
  <fieldset>
    <span class="label">Status</span>
    <div class="boxes">{statuses}</div>
  </fieldset>
  <fieldset>
    <span class="label">Priority</span>
    <div class="boxes">{priorities}</div>
  </fieldset>
  <fieldset>
    <span class="label">Severity</span>
    <div class="boxes">{severities}</div>
  </fieldset>
  <fieldset>
    <span class="label">Parent</span>
    <div class="boxes">{parents}</div>
  </fieldset>
  <fieldset>
    <span class="label">Created on or after</span>
    <input type="date" name="created" value="{created}">
  </fieldset>
  <fieldset>
    <span class="label">Labels in</span>
    <input type="text" name="labels" value="{labels}" placeholder="a,b"
           autocomplete="off" data-lpignore="true" data-1p-ignore>
  </fieldset>
  <fieldset>
    <span class="label">Labels not in</span>
    <input type="text" name="not_labels" value="{not_labels}" placeholder="a,b"
           autocomplete="off" data-lpignore="true" data-1p-ignore>
  </fieldset>
  <fieldset>
    <span class="label">Columns</span>
    <div class="boxes" id="columns">{columns}</div>
  </fieldset>
  <div class="buttons">
    <button type="submit" title="Reload the table with the filters as set">
      Apply filters</button>
    <button type="submit" name="force" value="1"
            title="Fetch the latest tickets from Jira, then apply the filters">
      Fetch from Jira</button>
    <a href="/" title="Back to the default filters">Defaults</a>
  </div>
</form>
<table>
<thead><tr>{headers}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
<div id="modal" hidden>
  <div id="modal-box">
    <button id="modal-close" type="button">Close</button>
    <div id="modal-content"></div>
  </div>
</div>
{tickets}
<script>
  // Clicking a sortable header sorts the rows by that column, descending
  // first and ascending on the next click; the arrow shows the direction.
  // The rows carry the sort keys in data-sort-<column> attributes.
  const tbody = document.querySelector("tbody");
  document.querySelectorAll("th.sortable").forEach(th => {{
    th.addEventListener("click", () => {{
      const descending = th.dataset.dir !== "desc";
      document.querySelectorAll("th.sortable").forEach(other => {{
        delete other.dataset.dir;
        other.querySelector(".arrow").textContent = "";
      }});
      th.dataset.dir = descending ? "desc" : "asc";
      th.querySelector(".arrow").textContent = descending ? "\\u25BC" : "\\u25B2";
      const key = "sort" + th.dataset.sort[0].toUpperCase() + th.dataset.sort.slice(1);
      const rows = Array.from(tbody.querySelectorAll("tr")).filter(r => key in r.dataset);
      rows.sort((a, b) => {{
        const x = a.dataset[key], y = b.dataset[key];
        const cmp = x < y ? -1 : x > y ? 1 : 0;
        return descending ? -cmp : cmp;
      }});
      rows.forEach(r => tbody.appendChild(r));
    }});
  }});
  // Dragging a header onto another moves the column there. The column check
  // boxes are kept in the shown order and submit in that order, so moving
  // the dragged column's box and submitting the form keeps the new order.
  let dragged = null;
  const columnBox = c => document.querySelector('#columns input[value="' + c + '"]').parentNode;
  document.querySelectorAll("th[data-column]").forEach(th => {{
    th.addEventListener("dragstart", e => {{
      dragged = th.dataset.column;
      e.dataTransfer.effectAllowed = "move";
    }});
    th.addEventListener("dragover", e => {{ e.preventDefault(); th.classList.add("over"); }});
    th.addEventListener("dragleave", () => th.classList.remove("over"));
    th.addEventListener("drop", e => {{
      e.preventDefault();
      th.classList.remove("over");
      const target = th.dataset.column;
      if (!dragged || dragged === target) return;
      const shown = Array.from(document.querySelectorAll("th[data-column]"), h => h.dataset.column);
      const from = columnBox(dragged), to = columnBox(target);
      if (shown.indexOf(dragged) < shown.indexOf(target)) to.after(from); else to.before(from);
      from.querySelector("input").form.submit();
    }});
  }});
  // Check boxes and the date apply as soon as they change; text fields on Enter.
  document.querySelectorAll(
    "#filters input[type=checkbox]:not([name=assignee]), #filters input[type=date]")
    .forEach(el => el.addEventListener("change", () => el.form.submit()));
  // The assignee dropdown: a change of people refetches from Jira, so it
  // applies when the list closes rather than on every tick. The search box
  // narrows the list; it has no name, so it isn't part of the filters.
  const who = document.getElementById("who");
  const whoSearch = document.getElementById("who-search");
  const whoBoxes = Array.from(who.querySelectorAll("input[type=checkbox]"));
  const picked = () => whoBoxes.filter(b => b.checked);
  const pickedAtLoad = picked().map(b => b.value).join();
  whoBoxes.forEach(b => b.addEventListener("change", () => {{
    who.querySelector("summary").textContent =
      picked().map(p => p.parentNode.textContent.trim()).join(", ") || "Me";
  }}));
  who.addEventListener("toggle", () => {{
    if (who.open) whoSearch.focus();
    else if (picked().map(b => b.value).join() !== pickedAtLoad)
      document.getElementById("filters").submit();
  }});
  whoSearch.addEventListener("input", () => {{
    const q = whoSearch.value.trim().toLowerCase();
    whoBoxes.forEach(b =>
      b.parentNode.hidden = !b.parentNode.textContent.toLowerCase().includes(q));
  }});
  document.addEventListener("click", e => {{
    if (who.open && !who.contains(e.target)) who.open = false;
  }});
  const modal = document.getElementById("modal");
  const content = document.getElementById("modal-content");
  function openTicket(key) {{
    content.innerHTML = document.getElementById("t-" + key).innerHTML;
    content.querySelectorAll("a").forEach(a => a.target = "_blank");
    modal.hidden = false;
    content.scrollTop = 0;
    loadSummary(key, content.querySelector(".summary"));
  }}
  // The preview starts with a short summary of the ticket, asked of the
  // server each time the preview opens; the server writes it once and
  // saves it.
  async function loadSummary(key, box) {{
    try {{
      const resp = await fetch("/summary?key=" + encodeURIComponent(key));
      const summary = await resp.json();
      box.textContent = summary.text || "(No summary: " + summary.error + ")";
      box.classList.toggle("empty", !summary.text);
    }} catch (e) {{
      box.textContent = "(No summary: " + e.message + ")";
    }}
  }}
  // The key and title open the real Jira page in one separate browser
  // window, reused for every ticket, so changes can be made there. Jira
  // refuses to be embedded in the page (X-Frame-Options: SAMEORIGIN), so
  // a window is the closest thing to an editable popup. Modified clicks
  // (Cmd, Ctrl, Shift, middle) keep the browser's own tab behaviour.
  document.querySelectorAll("a.open").forEach(a =>
    a.addEventListener("click", e => {{
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
      e.preventDefault();
      const win = window.open(a.href, "jira-ticket", "popup,width=1200,height=900");
      if (win) win.focus();
    }}));
  // The preview icon shows the cached, read-only copy without leaving the page.
  document.querySelectorAll("[data-key]").forEach(el =>
    el.addEventListener("click", e => {{ e.preventDefault(); openTicket(el.dataset.key); }}));
  document.getElementById("modal-close").addEventListener("click", () => modal.hidden = true);
  modal.addEventListener("click", e => {{ if (e.target === modal) modal.hidden = true; }});
  document.addEventListener("keydown", e => {{
    if (e.key === "Escape") {{ modal.hidden = true; who.open = false; }}
  }});
</script>
</body>
</html>
"""


def first(query, name):
    return query.get(name, [""])[0].strip()


def filter_args(query):
    """Turn the page's query string into the arguments select_rows() takes.
    Without the hidden "f" field (a fresh page) the defaults apply; with it,
    an unchecked group means everything."""
    explicit = "f" in query
    columns = [c for c in query.get("columns", []) if c in digest.COLUMNS]
    return argparse.Namespace(
        # One value per ticked person; a typed URL may also list several
        # names in one value, comma separated.
        assignee=[
            n for v in query.get("assignee", []) for n in digest.parse_names(v)
        ],
        project={p.lower() for p in query.get("project", [])},
        status={s.lower() for s in query.get("status", [])}
        if explicit else digest.parse_list(digest.DEFAULT_STATUSES),
        priority={p.lower() for p in query.get("priority", [])},
        severity={s.lower() for s in query.get("severity", [])},
        parent={p.lower() for p in query.get("parent", [])},
        created=(first(query, "created") or None) if explicit else digest.start_of_year(),
        labels=digest.parse_list(first(query, "labels")),
        not_labels=digest.parse_list(first(query, "not_labels"))
        if explicit else digest.parse_list(digest.DEFAULT_NOT_LABELS),
        columns=digest.with_always_column(columns or digest.DEFAULT_COLUMNS),
    )


def cache_note():
    if not digest.CACHE_FILE.exists():
        return ""
    age = int((time.time() - digest.CACHE_FILE.stat().st_mtime) // 60)
    return f"Data fetched {age} min ago."


def jira_html(html):
    """Make Jira's rendered HTML safe to embed: no scripts, absolute links."""
    return RELATIVE_URL.sub(rf'\1="{digest.JIRA}/', SCRIPT_TAG.sub("", html or ""))


def chips(values):
    return "".join(f'<span class="chip">{escape(v)}</span>' for v in values) or "-"


def severity_html(severity):
    if not severity:
        return "-"
    return f'<span class="sev-{escape(severity.lower())}">{escape(severity)}</span>'


def cell_html(row, column):
    if column == "ticket":
        return (
            f'<a class="key open" href="{escape(row["url"])}"'
            f' title="Open the ticket in Jira in a separate window">{escape(row["key"])}</a>'
            f'<a class="jira" href="#" data-key="{escape(row["key"])}"'
            f' title="Quick read-only preview">&#9432;</a>'
        )
    if column == "title":
        return (
            f'<a class="title open" href="{escape(row["url"])}"'
            f' title="Open the ticket in Jira in a separate window">{escape(row["summary"])}</a>'
        )
    if column == "assignee":
        if not row["assignee"]:
            return "-"
        return (
            f'<span title="{escape(row["assignee"])}">'
            f'{escape(digest.initials(row["assignee"]))}</span>'
        )
    if column == "severity":
        return severity_html(row["severity"])
    if column == "parent":
        if not row["parent"]:
            return "-"
        return (
            f'<a class="open" href="{escape(digest.BROWSE + row["parent"])}"'
            f' title="{escape(row["parent_summary"])}">{escape(row["parent"])}</a>'
        )
    if column in ("labels", "fixversions", "components"):
        return chips(row[column])
    return escape(digest.cell_text(row, column))


NOWRAP = {"ticket", "assignee", "status", "severity", "parent", "created", "updated", "priority", "type", "project"}


SORTABLE = ["ticket", "status", "severity", "priority"]


def sort_keys(row):
    """The data attributes the page's column sorting compares as strings:
    tickets by project and then number, statuses by name, and severities
    and priorities so that a bigger key is more severe or higher."""
    project, number = row["key"].rsplit("-", 1)
    return (
        f' data-sort-ticket="{escape(project)}-{int(number):06d}"'
        f' data-sort-status="{escape(row["status"].lower())}"'
        f' data-sort-severity="{9 - digest.severity_rank(row["severity"])}"'
        f' data-sort-priority="{99 - digest.priority_rank(row["priority"]):02d}"'
    )


def header_html(column):
    attrs = f'data-column="{column}" draggable="true"'
    if column not in SORTABLE:
        return (
            f'<th {attrs} title="Drag to move this column">'
            f"{escape(digest.COLUMNS[column])}</th>"
        )
    return (
        f'<th class="sortable" data-sort="{column}" {attrs}'
        f' title="Click to sort by this column, drag to move it">'
        f'{escape(digest.COLUMNS[column])} <span class="arrow"></span></th>'
    )


def table_rows(rows, columns):
    if not rows:
        return f'<tr><td colspan="{len(columns)}">No tickets match these filters.</td></tr>'
    return "\n".join(
        f"<tr{sort_keys(r)}>"
        + "".join(
            f'<td class="{"nowrap" if c in NOWRAP else ""}">{cell_html(r, c)}</td>'
            for c in columns
        )
        + "</tr>"
        for r in rows
    )


def ticket_html(row):
    """The hidden popup content for one ticket."""
    facts = [
        ("Project", f'{row["project"]} ({row["project_name"]})'),
        ("Type", row["type"]),
        ("Status", row["status"]),
        ("Priority", row["priority"]),
        ("Severity", row["severity"]),
        ("Parent", f'{row["parent"]} {row["parent_summary"]}'.strip()),
        ("Assignee", row["assignee"]),
        ("Reporter", row["reporter"]),
        ("Created", row["created"]),
        ("Updated", row["updated"]),
        ("Labels", ", ".join(row["labels"])),
        ("Fix versions", ", ".join(row["fixversions"])),
        ("Components", ", ".join(row["components"])),
        ("Resolution", row["resolution"]),
    ]
    dl = "".join(
        f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in facts if v
    )
    description = (
        f'<div class="body">{jira_html(row["description"])}</div>'
        if row["description"].strip()
        else '<div class="empty">(no description)</div>'
    )
    comments = "".join(
        f'<div class="comment"><div class="who">{escape(c["author"])}, {escape(c["created"])}</div>'
        f'<div class="body">{jira_html(c["body"])}</div></div>'
        for c in row["comments"]
    )
    heading = f"Comments ({row['comment_total']})"
    if row["comment_total"] > len(row["comments"]):
        heading += f", showing the first {len(row['comments'])}"
    return (
        f'<div class="ticket" id="t-{escape(row["key"])}" hidden>'
        f'<h2><a href="{escape(row["url"])}">{escape(row["key"])}</a> {escape(row["summary"])}</h2>'
        f"<dl>{dl}</dl>"
        '<h3>Summary</h3><div class="body summary empty">Summarizing...</div>'
        f"<h3>Description</h3>{description}"
        f"<h3>{escape(heading)}</h3>{comments or '<div class=empty>(none)</div>'}"
        "</div>"
    )


def ticket_summary_of(key, data):
    """Return a ticket's summary as {"title", "text"}: the saved one, or one
    written now from the loaded ticket and saved. Returns {"error"} when
    there is no saved summary and one can't be written."""
    found = ticket_summary.saved(key)
    if found:
        return found
    row = next((t for t in (data or {}).get("tickets", []) if t["key"] == key), None)
    if row is None:
        return {"error": f"{key} isn't among the loaded tickets"}
    try:
        return ticket_summary.summary(
            key, row["summary"], ticket_summary.plain_text(row["description"])
        )
    except RuntimeError as e:
        return {"error": str(e)}


def boxes(name, options, chosen, fixed=()):
    """Check boxes named name for (value, label) options; chosen holds the
    lower case values that are ticked, fixed the ones that can't change."""
    if not options:
        return "(none)"
    out = []
    for v, label in options:
        title = ' title="Always shown"' if v in fixed else ""
        checked = " checked" if v.lower() in chosen else ""
        disabled = " disabled" if v in fixed else ""
        out.append(
            f'<label{title}><input type="checkbox" name="{escape(name)}"'
            f' value="{escape(v)}"{checked}{disabled}> {escape(label)}</label>'
        )
    return "".join(out)


def project_options(data):
    names = {t["project"]: t["project_name"] for t in data["tickets"]}
    keys = digest.PROJECTS + sorted(set(names) - set(digest.PROJECTS))
    return [(k, f"{k} {names[k]}" if k in names else k) for k in keys]


def status_options(data):
    seen = {t["status"] for t in data["tickets"]}
    defaults = [s for s in digest.DEFAULT_STATUSES.split(",")]
    return [(s, s) for s in defaults + sorted(seen - set(defaults), key=str.lower)]


def severity_options(data):
    return ranked_options({t["severity"] for t in data["tickets"]}, digest.SEVERITY_ORDER)


def priority_options(data):
    return ranked_options({t["priority"] for t in data["tickets"]}, digest.PRIORITY_ORDER)


def ranked_options(seen, order):
    """The values in seen that are in order, in that order, then the rest
    alphabetically, then "(none)"."""
    seen = {s for s in seen if s}
    lower = {s.lower() for s in seen}
    known = [s for s in order if s.lower() in lower]
    extra = sorted(s for s in seen if s.lower() not in {k.lower() for k in order})
    return [(s, s) for s in known + extra] + [("none", "(none)")]


def parent_options(data):
    """The parents of the tickets in the data, as "KEY summary", sorted by
    project and number, plus "(none)" for tickets without one."""
    names = {t["parent"]: t["parent_summary"] for t in data["tickets"] if t["parent"]}

    def order(key):
        project, number = key.rsplit("-", 1)
        return (project, int(number) if number.isdigit() else 0)

    keys = sorted(names, key=order)
    return [(k, f"{k} {names[k]}".strip()) for k in keys] + [("none", "(none)")]


def column_options(shown):
    """The columns in the order they are shown, then the hidden ones; the
    check boxes submit in this order, which sets the column order."""
    order = list(shown) + [c for c in digest.COLUMNS if c not in shown]
    return [(c, digest.COLUMNS[c]) for c in order]


def assignee_options(data, users):
    """The assignee check boxes and the lower case values that are ticked:
    "me" and "unassigned", then the Jira users by name, with their account
    ids as values. The people whose tickets are shown are listed even when
    users lacks them (the user fetch failed, or they can no longer be
    assigned), so that they can be unticked."""
    me = data["me"]
    people = {u["id"]: u["name"] for u in users}
    chosen = set()
    for a in data["assignees"]:
        if a["id"] is None:
            chosen.add("unassigned")
        elif a["id"] == me["id"]:
            chosen.add("me")
        else:
            chosen.add(a["id"].lower())
            people.setdefault(a["id"], a["name"])
    people.pop(me["id"], None)
    options = [("me", f'Me ({me["name"]})'), ("unassigned", "Unassigned")]
    options += sorted(people.items(), key=lambda p: p[1].lower())
    return options, chosen


def render(query, data, users, error=""):
    args = filter_args(query)
    title, rows = digest.select_rows(data, args)
    people, chosen = assignee_options(data, users)
    return PAGE.format(
        title=escape(title),
        cache=escape(cache_note()),
        error=f'<div class="failure">{escape(error)}</div>' if error else "",
        assignee=escape(
            ", ".join(label for v, label in people if v.lower() in chosen)
        ),
        assignees=boxes("assignee", people, chosen),
        projects=boxes("project", project_options(data), args.project),
        statuses=boxes("status", status_options(data), args.status),
        priorities=boxes("priority", priority_options(data), args.priority),
        severities=boxes("severity", severity_options(data), args.severity),
        parents=boxes("parent", parent_options(data), args.parent),
        created=escape(args.created or ""),
        labels=escape(", ".join(sorted(args.labels))),
        not_labels=escape(", ".join(sorted(args.not_labels))),
        columns=boxes(
            "columns", column_options(args.columns), set(args.columns),
            fixed={digest.ALWAYS_COLUMN},
        ),
        headers="".join(header_html(c) for c in args.columns),
        rows=table_rows(rows, args.columns),
        tickets="\n".join(ticket_html(r) for r in rows),
    )


class Handler(BaseHTTPRequestHandler):
    auth = None
    data = None  # the last ticket data loaded
    users = []  # the last list of assignable people loaded
    lock = threading.Lock()  # one fetch at a time

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/summary":
            self.send_summary(first(query, "key"))
            return
        if url.path != "/":
            self.send_error(404)
            return
        args = filter_args(query)
        if "force" in query:
            error = self.load(args, force=True)
            if not error:
                # Drop force from the URL so reloading the page doesn't refetch.
                del query["force"]
                self.send_response(303)
                self.send_header("Location", "/?" + urlencode(query, doseq=True))
                self.end_headers()
                return
        else:
            error = self.load(args, force=False)
        if Handler.data is None:
            self.send_error(500, explain=error)
            return
        body = render(query, Handler.data, Handler.users, error).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_summary(self, key):
        """Answer the preview's request for a ticket's summary with JSON:
        {"title", "text"}, or {"error"} when there is none to give."""
        body = json.dumps(ticket_summary_of(key, Handler.data)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def load(self, args, force):
        """Load the ticket data into Handler.data and the assignable people
        into Handler.users, and return an error message, or "" on success.
        On failure the last good data is kept."""
        errors = []
        with Handler.lock:
            try:
                Handler.data = digest.load_data(
                    Handler.auth, force, args.assignee, args.created
                )
            except Exception as e:  # show any fetch failure on the page
                errors.append(f"Fetching from Jira failed: {e}")
            try:
                Handler.users = digest.load_users(Handler.auth)
            except Exception as e:
                errors.append(f"Fetching the assignee list from Jira failed: {e}")
        return "\n".join(errors)

    def log_message(self, fmt, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Serve the Jira digest as a web page.")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    Handler.auth = digest.auth_header()
    # Threads, so that a browser's idle keep-alive or preconnect sockets
    # don't block other requests; Handler.lock keeps fetches one at a time.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Serving {url} (Ctrl-C to stop)", file=sys.stderr)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
