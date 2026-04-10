"""Server-rendered admin console for the compiled knowledge layer."""

from __future__ import annotations

from html import escape
from typing import Any, Iterable


_BASE_CSS = """
:root {
  --bg: #f4efe7;
  --surface: #fffdf8;
  --surface-strong: #fff7eb;
  --surface-ink: #1f1a17;
  --line: #ddcfbb;
  --line-strong: #b99666;
  --accent: #a44718;
  --accent-soft: #f6e1cf;
  --success: #1f6a3a;
  --warning: #8a4a12;
  --danger: #942626;
  --muted: #665d55;
  --shadow: 0 18px 50px rgba(74, 43, 18, 0.08);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  color: var(--surface-ink);
  background:
    radial-gradient(circle at top left, rgba(164, 71, 24, 0.10), transparent 28rem),
    linear-gradient(180deg, #f8f1e8 0%, var(--bg) 55%, #efe5d7 100%);
  font-family: "Avenir Next", "Segoe UI", sans-serif;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  background: #f4ecdf;
  border-radius: 0.45rem;
}
code { padding: 0.15rem 0.35rem; }
pre {
  padding: 1rem;
  margin: 0;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
h1, h2, h3 {
  font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
  margin: 0 0 0.65rem;
  line-height: 1.1;
}
h1 { font-size: 2.4rem; }
h2 { font-size: 1.5rem; }
h3 { font-size: 1.08rem; }
p { margin: 0.4rem 0 0; line-height: 1.55; }
ul { margin: 0.45rem 0 0; padding-left: 1.2rem; }
table { border-collapse: collapse; width: 100%; }
th, td {
  border-bottom: 1px solid var(--line);
  text-align: left;
  padding: 0.75rem 0.55rem;
  vertical-align: top;
}
th { color: var(--muted); font-size: 0.82rem; letter-spacing: 0.03em; text-transform: uppercase; }
button {
  appearance: none;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  background: var(--surface);
  color: var(--surface-ink);
  padding: 0.55rem 0.95rem;
  cursor: pointer;
  font-weight: 600;
}
button.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff8ef;
}
button.danger {
  background: var(--danger);
  border-color: var(--danger);
  color: #fff3f1;
}
form.inline { display: inline; }
.shell {
  width: min(1200px, calc(100vw - 2.4rem));
  margin: 1.4rem auto 2.8rem;
}
.hero {
  border: 1px solid rgba(185, 150, 102, 0.8);
  border-radius: 1.75rem;
  padding: 1.4rem 1.5rem 1.25rem;
  background:
    linear-gradient(135deg, rgba(255, 247, 235, 0.95), rgba(255, 253, 248, 0.98)),
    var(--surface);
  box-shadow: var(--shadow);
}
.eyebrow {
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 0.72rem;
  font-weight: 700;
}
.hero-grid, .metrics, .split, .cards {
  display: grid;
  gap: 1rem;
}
.hero-grid { grid-template-columns: 1.8fr 1fr; align-items: end; }
.metrics { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); margin-top: 1rem; }
.cards { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.split { grid-template-columns: 1.25fr 1fr; }
.panel, .metric, .tile, .spotlight {
  border: 1px solid rgba(185, 150, 102, 0.6);
  border-radius: 1.25rem;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.panel, .tile, .spotlight { padding: 1.15rem 1.2rem; }
.metric {
  padding: 0.9rem 1rem 1rem;
  background: linear-gradient(180deg, var(--surface-strong), var(--surface));
}
.metric strong {
  display: block;
  font-size: 1.8rem;
  margin-top: 0.35rem;
}
.metric span, .small, .meta, .empty { color: var(--muted); }
.section { margin-top: 1.15rem; }
.section-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1rem;
  margin-bottom: 0.8rem;
}
.topnav {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin-top: 1rem;
}
.topnav a {
  display: inline-flex;
  align-items: center;
  border: 1px solid rgba(185, 150, 102, 0.65);
  border-radius: 999px;
  padding: 0.55rem 0.9rem;
  background: rgba(255, 253, 248, 0.7);
  color: var(--surface-ink);
  font-weight: 600;
}
.topnav a.active {
  background: var(--surface-ink);
  border-color: var(--surface-ink);
  color: #fff7ee;
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  border-radius: 999px;
  padding: 0.26rem 0.58rem;
  font-size: 0.78rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border: 1px solid rgba(31, 26, 23, 0.10);
}
.status::before {
  content: "";
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 999px;
  background: currentColor;
}
.status-pending { color: var(--warning); background: #fff0df; }
.status-applied { color: var(--success); background: #e8f6ec; }
.status-rejected, .status-conflicted { color: var(--danger); background: #fdeceb; }
.status-ready, .status-running, .status-superseded { color: #5e6073; background: #ececf3; }
.inline-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.85rem;
}
.pill {
  border-radius: 999px;
  background: var(--accent-soft);
  padding: 0.35rem 0.6rem;
  color: var(--accent);
  font-weight: 600;
  font-size: 0.84rem;
}
.activity {
  list-style: none;
  margin: 0;
  padding: 0;
}
.activity li {
  padding: 0.8rem 0;
  border-bottom: 1px solid var(--line);
}
.activity li:last-child { border-bottom: 0; }
.activity strong { display: block; }
.kv {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 0.45rem 0.8rem;
  margin-top: 0.8rem;
}
.kv dt {
  color: var(--muted);
  font-size: 0.82rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.kv dd { margin: 0; }
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.65rem;
  margin-top: 1rem;
}
.stack { display: grid; gap: 1rem; }
.raw-box { max-height: 28rem; overflow: auto; }
@media (max-width: 920px) {
  .hero-grid, .split { grid-template-columns: 1fr; }
}
"""

_NAV_ITEMS = (
    ("home", "/ui/knowledge/", "Home"),
    ("review", "/ui/knowledge/proposals", "Review"),
    ("sources", "/ui/knowledge/sources", "Sources"),
    ("library", "/ui/knowledge/library", "Library"),
    ("operations", "/ui/knowledge/operations", "Operations"),
    ("logs", "/ui/knowledge/logs", "Logs"),
)


def _page(*, title: str, active: str, eyebrow: str, heading: str, summary: str, body: str) -> str:
    hero = (
        '<div class="hero">'
        f'<div class="eyebrow">{escape(eyebrow)}</div>'
        '<div class="hero-grid">'
        "<div>"
        f"<h1>{escape(heading)}</h1>"
        f"<p>{escape(summary)}</p>"
        "</div>"
        '<div class="spotlight">'
        "<h3>Built-in role</h3>"
        "<p>Operate and inspect Synapse without turning the core project into a full client application.</p>"
        "</div>"
        "</div>"
        f"{_nav(active)}"
        "</div>"
    )
    return (
        "<!doctype html>\n"
        f"<html><head><meta charset=\"utf-8\"><title>{escape(title)}</title>"
        f"<style>{_BASE_CSS}</style></head><body>"
        f'<div class="shell">{hero}{body}</div></body></html>'
    )


def _nav(active: str) -> str:
    links = []
    for key, href, label in _NAV_ITEMS:
        css = "active" if key == active else ""
        links.append(f'<a class="{css}" href="{href}">{escape(label)}</a>')
    return f'<nav class="topnav">{"".join(links)}</nav>'


def _status_span(status: str) -> str:
    safe = escape(status)
    return f'<span class="status status-{safe}">{safe}</span>'


def _panel(title: str, body: str, *, subtitle: str | None = None) -> str:
    subtitle_html = f'<p class="small">{escape(subtitle)}</p>' if subtitle else ""
    return f'<section class="panel"><h2>{escape(title)}</h2>{subtitle_html}{body}</section>'


def _metric(label: str, value: int | str, detail: str) -> str:
    return (
        '<div class="metric">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(str(value))}</strong>"
        f"<p class=\"small\">{escape(detail)}</p>"
        "</div>"
    )


def _activity_list(items: Iterable[str], *, empty: str) -> str:
    rows = [f"<li>{item}</li>" for item in items]
    if not rows:
        rows = [f'<li class="empty">{escape(empty)}</li>']
    return f'<ul class="activity">{"".join(rows)}</ul>'


def _render_proposal_rows(rows: Iterable[dict[str, Any]], *, empty_text: str) -> str:
    parts = []
    for row in rows:
        source = row.get("supporting_refs") or {}
        source_link = ""
        bundle_id = source.get("bundle_id")
        source_id = source.get("source_id")
        if bundle_id and source_id:
            source_link = (
                f'<a href="/ui/knowledge/sources/{escape(str(bundle_id))}/{escape(str(source_id))}">'
                f"{escape(str(source_id))}</a>"
            )
        parts.append(
            "<tr>"
            f"<td>#{int(row['id'])}</td>"
            f"<td>{escape(str(row.get('note_kind', '')))}</td>"
            f"<td><a href=\"/ui/knowledge/proposals/{int(row['id'])}\">"
            f"{escape(str(row.get('title') or row.get('target_path', '')))}</a></td>"
            f"<td>{_status_span(str(row.get('status', 'pending')))}</td>"
            f"<td>{source_link or '<span class=\"small\">-</span>'}</td>"
            f"<td><code>{escape(str(row.get('target_path', '')))}</code></td>"
            "</tr>"
        )
    if not parts:
        parts.append(f'<tr><td colspan="6" class="empty">{escape(empty_text)}</td></tr>')
    return "".join(parts)


def _render_segment_groups(segments: Iterable[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        grouped.setdefault(str(segment.get("content_role") or "other"), []).append(segment)
    if not grouped:
        return '<p class="empty">No stored source segments yet.</p>'

    sections: list[str] = []
    for role in ("summary", "abstract", "full_text"):
        if role not in grouped:
            continue
        cards = []
        for segment in sorted(grouped[role], key=lambda item: int(item.get("segment_index", 0))):
            cards.append(
                '<article class="tile">'
                f'<div class="section-head"><h3>{escape(role.replace("_", " ").title())} chunk {int(segment.get("segment_index", 0)) + 1}</h3>'
                f'<span class="small">segment #{int(segment.get("id", 0))}</span></div>'
                f'<pre>{escape(str(segment.get("text") or ""))}</pre>'
                "</article>"
            )
        sections.append(
            f'<section class="section"><div class="section-head"><h2>{escape(role.replace("_", " ").title())}</h2>'
            f'<span class="small">{len(grouped[role])} chunk(s)</span></div>'
            f'<div class="stack">{"".join(cards)}</div></section>'
        )
    for role in sorted(grouped):
        if role in {"summary", "abstract", "full_text"}:
            continue
        cards = []
        for segment in sorted(grouped[role], key=lambda item: int(item.get("segment_index", 0))):
            cards.append(
                '<article class="tile">'
                f'<div class="section-head"><h3>{escape(role.replace("_", " ").title())} chunk {int(segment.get("segment_index", 0)) + 1}</h3>'
                f'<span class="small">segment #{int(segment.get("id", 0))}</span></div>'
                f'<pre>{escape(str(segment.get("text") or ""))}</pre>'
                "</article>"
            )
        sections.append(
            f'<section class="section"><div class="section-head"><h2>{escape(role.replace("_", " ").title())}</h2>'
            f'<span class="small">{len(grouped[role])} chunk(s)</span></div>'
            f'<div class="stack">{"".join(cards)}</div></section>'
        )
    return "".join(sections)


def render_overview_page(
    *,
    managed_root: str,
    vault_root: str,
    counts: dict[str, int],
    recent_proposals: Iterable[dict[str, Any]],
) -> str:
    counts = dict(counts)
    pending = int(counts.get("pending", 0))
    applied = int(counts.get("applied", 0))
    rejected = int(counts.get("rejected", 0))
    conflicted = int(counts.get("conflicted", 0))
    metrics = (
        _metric("Pending review", pending, "Items waiting for operator action")
        + _metric("Applied notes", applied, "Compiled notes already written to the managed wiki")
        + _metric("Rejected", rejected, "Proposals intentionally kept out of the library")
        + _metric("Conflicts", conflicted, "Items that need regeneration before they can be applied")
    )
    activity = []
    for row in recent_proposals:
        activity.append(
            f"<strong>{escape(str(row.get('title') or row.get('target_path') or 'Untitled proposal'))}</strong>"
            f"<span class=\"small\">{_status_span(str(row.get('status', 'pending')))} "
            f"· {escape(str(row.get('note_kind', '')))} "
            f"· <code>{escape(str(row.get('target_path', '')))}</code></span>"
        )
    attention = []
    if pending:
        attention.append(f"{pending} proposal(s) are waiting in <a href=\"/ui/knowledge/proposals\">Review</a>.")
    if conflicted:
        attention.append(f"{conflicted} proposal(s) are conflicted and need regeneration or manual inspection.")
    if not attention:
        attention.append("No urgent review pressure right now. Check <a href=\"/ui/knowledge/operations\">Operations</a> for recent changes.")

    recent_table = (
        "<table><thead><tr>"
        "<th>ID</th><th>Kind</th><th>Title</th><th>Status</th><th>Source</th><th>Target</th>"
        "</tr></thead><tbody>"
        f"{_render_proposal_rows(recent_proposals, empty_text='No recent activity yet.')}"
        "</tbody></table>"
    )

    body = (
        '<section class="section metrics">'
        f"{metrics}"
        "</section>"
        '<section class="section split">'
        f"{_panel('System footprint', ''.join((
            '<dl class=\"kv\">',
            '<dt>Managed root</dt><dd><code>' + escape(managed_root) + '</code></dd>',
            '<dt>Vault root</dt><dd><code>' + escape(vault_root) + '</code></dd>',
            '<dt>Primary workflow</dt><dd>Ingest -> compile -> review -> apply -> inspect -> maintain</dd>',
            '</dl>',
        )))}"
        f"{_panel('Needs attention', _activity_list(attention, empty='No alerts.'))}"
        "</section>"
        '<section class="section split">'
        f"{_panel('Recent activity', _activity_list(activity, empty='No proposal activity yet.'), subtitle='Latest compile and review artifacts visible in the knowledge layer.')}"
        f"{_panel('Operator lanes', ''.join((
            '<div class=\"inline-list\">',
            '<span class=\"pill\">Review</span>',
            '<span class=\"pill\">Sources</span>',
            '<span class=\"pill\">Library</span>',
            '<span class=\"pill\">Operations</span>',
            '<span class=\"pill\">Logs</span>',
            '</div>',
            '<p class=\"small\">Each view corresponds to an internal workflow instead of exposing raw tables.</p>',
        )))}"
        "</section>"
        f'<section class="section">{_panel("Recent items", recent_table)}</section>'
    )
    return _page(
        title="Knowledge Home",
        active="home",
        eyebrow="Synapse Knowledge Admin",
        heading="Knowledge Home",
        summary="Monitor the compiled knowledge workflow, surface what needs review, and trace generated artifacts back to their operational context.",
        body=body,
    )


def render_source_detail_page(
    *,
    bundle_id: str,
    source_id: str,
    source: dict[str, Any],
    related_proposals: Iterable[dict[str, Any]],
    segments: Iterable[dict[str, Any]],
) -> str:
    title = str(source.get("title") or source_id)
    authors = ", ".join(source.get("authors") or []) or "-"
    related_proposals = list(related_proposals)
    segments = list(segments)
    proposal_count = len(related_proposals)
    related_rows = _render_proposal_rows(
        related_proposals,
        empty_text="This source has not produced any compiled proposals yet.",
    )
    body = (
        '<section class="section split">'
        f"{_panel('Source identity', ''.join((
            '<dl class=\"kv\">',
            '<dt>Bundle</dt><dd><a href=\"/ui/knowledge/bundles/' + escape(bundle_id) + '\"><code>' + escape(bundle_id) + '</code></a></dd>',
            '<dt>Source ID</dt><dd><code>' + escape(source_id) + '</code></dd>',
            '<dt>Source type</dt><dd>' + escape(str(source.get('source_type') or '-')) + '</dd>',
            '<dt>Origin URL</dt><dd>' + escape(str(source.get('origin_url') or '-')) + '</dd>',
            '<dt>Paper URL</dt><dd>' + escape(str(source.get('direct_paper_url') or '-')) + '</dd>',
            '<dt>Published</dt><dd>' + escape(str(source.get('published') or '-')) + '</dd>',
            '<dt>Authors</dt><dd>' + escape(authors) + '</dd>',
            '</dl>',
        )))}"
        f"{_panel('Contribution summary', ''.join((
            '<p>This page shows what Synapse learned from a single raw source and where that material surfaced in the compiled layer.</p>',
            '<div class=\"cards section\">',
            _metric('Related proposals', proposal_count, 'Compile and review artifacts tied to this source'),
            _metric('Applied notes', sum(1 for row in related_proposals if row.get('status') == 'applied'), 'Approved compiled notes linked back to this source'),
            _metric('Stored chunks', len(segments), 'Source segments available for inspection and retrieval'),
            '</div>',
        )))}"
        "</section>"
        f'<section class="section">{_panel("Source summary", "<pre>" + escape(str(source.get("summary_text") or "(no summary)")) + "</pre>", subtitle="This is the raw source-side summary currently stored in Synapse.")}</section>'
        f'<section class="section">{_panel("Source chunks", _render_segment_groups(segments), subtitle="Segments are grouped by content role so you can see exactly what ingest stored for retrieval.")}</section>'
        f'<section class="section">{_panel("Related review items", "<table><thead><tr><th>ID</th><th>Kind</th><th>Title</th><th>Status</th><th>Source</th><th>Target</th></tr></thead><tbody>" + related_rows + "</tbody></table>")}</section>'
    )
    return _page(
        title=f"Source {title}",
        active="sources",
        eyebrow="Sources",
        heading=title,
        summary="Inspect a raw source, verify its provenance, and trace the proposals and compiled notes that came out of it.",
        body=body,
    )


def render_note_detail_page(*, proposal: dict[str, Any]) -> str:
    frontmatter = proposal.get("frontmatter") or {}
    supporting_refs = proposal.get("supporting_refs") or {}
    body_markdown = str(proposal.get("body_markdown") or "")
    target_path = str(proposal.get("target_path") or "")
    bundle_id = supporting_refs.get("bundle_id")
    source_id = supporting_refs.get("source_id")
    status = str(proposal.get("status", "pending"))
    source_link = ""
    if bundle_id and source_id:
        source_link = (
            f'<a href="/ui/knowledge/sources/{escape(str(bundle_id))}/{escape(str(source_id))}">'
            f"{escape(str(source_id))}</a>"
        )

    action_buttons = ""
    if status == "pending":
        action_buttons = (
            f'<form class="inline" method="post" action="/ui/knowledge/proposals/{int(proposal["id"])}/apply">'
            '<button class="primary" type="submit">Approve and apply</button></form>'
            f'<form class="inline" method="post" action="/ui/knowledge/proposals/{int(proposal["id"])}/reject">'
            '<button class="danger" type="submit">Reject</button></form>'
        )

    frontmatter_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(str(key))}</strong></td>"
        f"<td><code>{escape(str(value))}</code></td>"
        "</tr>"
        for key, value in frontmatter.items()
    ) or '<tr><td colspan="2" class="empty">No frontmatter captured.</td></tr>'

    evidence_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(str(key))}</strong></td>"
        f"<td>{escape(str(value))}</td>"
        "</tr>"
        for key, value in supporting_refs.items()
        if value not in (None, "", [])
    ) or '<tr><td colspan="2" class="empty">No supporting references stored.</td></tr>'

    body = (
        '<section class="section split">'
        f"{_panel('Review context', ''.join((
            '<dl class=\"kv\">',
            '<dt>Proposal</dt><dd>#' + escape(str(proposal['id'])) + '</dd>',
            '<dt>Status</dt><dd>' + _status_span(status) + '</dd>',
            '<dt>Kind</dt><dd><code>' + escape(str(proposal.get('note_kind', ''))) + '</code></dd>',
            '<dt>Target path</dt><dd><code>' + escape(target_path) + '</code></dd>',
            '<dt>Source</dt><dd>' + (source_link or '-') + '</dd>',
            '<dt>Created</dt><dd>' + escape(str(proposal.get('created_at') or '-')) + '</dd>',
            '<dt>Updated</dt><dd>' + escape(str(proposal.get('updated_at') or '-')) + '</dd>',
            '</dl>',
            '<div class=\"actions\">' + action_buttons + '</div>',
        )))}"
        f"{_panel('Operator guidance', ''.join((
            '<p>Use this page to confirm that the target path, evidence, and note body make sense before changing the managed wiki.</p>',
            '<div class=\"inline-list\">',
            '<span class=\"pill\">Validate provenance</span>',
            '<span class=\"pill\">Inspect markdown</span>',
            '<span class=\"pill\">Approve or reject</span>',
            '</div>',
        )))}"
        "</section>"
        '<section class="section split">'
        f'{_panel("Supporting references", "<table><tbody>" + evidence_rows + "</tbody></table>")}'
        f'{_panel("Frontmatter", "<table><tbody>" + frontmatter_rows + "</tbody></table>")}'
        "</section>"
        f'<section class="section">{_panel("Draft markdown", "<pre>" + escape(body_markdown) + "</pre>", subtitle="The proposed note body that will be written into the managed wiki if approved.")}</section>'
    )
    return _page(
        title=f"Review Item #{proposal.get('id')}",
        active="review",
        eyebrow="Review",
        heading=f"Review Item #{proposal.get('id')}",
        summary="Inspect the compiled draft, confirm its provenance, and decide whether it should enter the managed knowledge library.",
        body=body,
    )


def render_proposal_queue_page(*, proposals: Iterable[dict[str, Any]]) -> str:
    proposals = list(proposals)
    pending = [row for row in proposals if row.get("status") == "pending"]
    recent = sorted(
        proposals,
        key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
        reverse=True,
    )
    queue_table = (
        "<table><thead><tr>"
        "<th>ID</th><th>Kind</th><th>Title</th><th>Status</th><th>Source</th><th>Target</th>"
        "</tr></thead><tbody>"
        f"{_render_proposal_rows(pending or recent, empty_text='No proposals in the review queue.')}"
        "</tbody></table>"
    )
    body = (
        '<section class="section metrics">'
        f'{_metric("Pending", len(pending), "Needs manual review before writing to the managed wiki")}'
        f'{_metric("All proposals", len(proposals), "Visible review history in this environment")}'
        "</section>"
        '<section class="section split">'
        f"{_panel('Review workflow', ''.join((
            '<p>This is the operator queue for compiled note proposals. Start here when you want to understand what Synapse is about to write.</p>',
            '<ul><li>Open the item.</li><li>Check provenance and target path.</li><li>Approve or reject.</li></ul>',
        )))}"
        f"{_panel('Current pressure', _activity_list([f'{len(pending)} item(s) are currently pending review.'], empty='No review pressure right now.'))}"
        "</section>"
        f'<section class="section">{_panel("Review queue", queue_table)}</section>'
    )
    return _page(
        title="Review Queue",
        active="review",
        eyebrow="Review",
        heading="Review Queue",
        summary="See what Synapse has compiled, verify the evidence, and control which notes get written into the managed knowledge library.",
        body=body,
    )


def render_sources_page(*, sources: Iterable[dict[str, Any]]) -> str:
    rows = []
    for row in sources:
        rows.append(
            "<tr>"
            f"<td><a href=\"/ui/knowledge/sources/{escape(str(row['bundle_id']))}/{escape(str(row['source_id']))}\">{escape(str(row.get('title') or row['source_id']))}</a></td>"
            f"<td><a href=\"/ui/knowledge/bundles/{escape(str(row['bundle_id']))}\"><code>{escape(str(row['bundle_id']))}</code></a></td>"
            f"<td><code>{escape(str(row['source_id']))}</code></td>"
            f"<td>{escape(str(row.get('proposal_count', 0)))}</td>"
            f"<td>{escape(str(row.get('applied_count', 0)))}</td>"
            f"<td>{escape(str(row.get('latest_status') or '-'))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6" class="empty">No source-linked proposals yet.</td></tr>')
    table = (
        "<table><thead><tr>"
        "<th>Title</th><th>Bundle</th><th>Source ID</th><th>Proposals</th><th>Applied</th><th>Latest status</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    body = f'<section class="section">{_panel("Tracked sources", table, subtitle="Grouped from proposal provenance so you can inspect how raw inputs map into the compiled layer.")}</section>'
    return _page(
        title="Sources",
        active="sources",
        eyebrow="Sources",
        heading="Sources",
        summary="Browse the raw inputs that are feeding the compiled knowledge layer and inspect how each source contributes to generated notes.",
        body=body,
    )


def render_bundle_detail_page(
    *,
    bundle_id: str,
    bundle: dict[str, Any],
    sources: Iterable[dict[str, Any]],
) -> str:
    sources = list(sources)
    rows = []
    for row in sources:
        rows.append(
            "<tr>"
            f"<td><a href=\"/ui/knowledge/sources/{escape(str(bundle_id))}/{escape(str(row['source_id']))}\">{escape(str(row.get('title') or row['source_id']))}</a></td>"
            f"<td><code>{escape(str(row['source_id']))}</code></td>"
            f"<td>{escape(str(row.get('source_type') or '-'))}</td>"
            f"<td>{escape(str(row.get('proposal_count', 0)))}</td>"
            f"<td>{escape(str(row.get('applied_count', 0)))}</td>"
            f"<td>{escape(str(row.get('latest_status') or '-'))}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6" class="empty">No sources found for this bundle.</td></tr>')
    table = (
        "<table><thead><tr>"
        "<th>Title</th><th>Source ID</th><th>Type</th><th>Proposals</th><th>Applied</th><th>Latest status</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    body = (
        '<section class="section split">'
        f"{_panel('Bundle identity', ''.join((
            '<dl class=\"kv\">',
            '<dt>Bundle ID</dt><dd><code>' + escape(bundle_id) + '</code></dd>',
            '<dt>Artifact path</dt><dd><code>' + escape(str(bundle.get('artifact_path') or '-')) + '</code></dd>',
            '<dt>Imported</dt><dd>' + escape(str(bundle.get('imported_at') or '-')) + '</dd>',
            '</dl>',
        )))}"
        f"{_panel('Bundle scope', ''.join((
            '<p>This bundle view shows the raw source set that Synapse ingested together, plus the review and apply activity attached to each source.</p>',
            '<div class=\"cards section\">',
            _metric('Sources', len(sources), 'Raw sources currently present in the bundle'),
            '</div>',
        )))}"
        "</section>"
        f'<section class="section">{_panel("Bundle sources", table, subtitle="Open a source to inspect its stored segments and review lineage.")}</section>'
    )
    return _page(
        title=f"Bundle {bundle_id}",
        active="sources",
        eyebrow="Bundles",
        heading=f"Bundle {bundle_id}",
        summary="Inspect the sources that arrived together in one ingest bundle and drill into each source's stored chunks and knowledge-layer activity.",
        body=body,
    )


def render_library_page(*, proposals: Iterable[dict[str, Any]]) -> str:
    proposals = list(proposals)
    by_kind: dict[str, int] = {}
    for row in proposals:
        by_kind[str(row.get("note_kind") or "unknown")] = by_kind.get(str(row.get("note_kind") or "unknown"), 0) + 1
    metric_html = "".join(
        _metric(kind.replace("_", " ").title(), count, "Applied notes in the managed library")
        for kind, count in sorted(by_kind.items())
    ) or _metric("Applied notes", 0, "No compiled notes have been approved yet.")
    table = (
        "<table><thead><tr>"
        "<th>ID</th><th>Kind</th><th>Title</th><th>Status</th><th>Source</th><th>Target</th>"
        "</tr></thead><tbody>"
        f"{_render_proposal_rows(proposals, empty_text='No applied compiled notes yet.')}"
        "</tbody></table>"
    )
    body = (
        f'<section class="section metrics">{metric_html}</section>'
        f'<section class="section">{_panel("Managed library", table, subtitle="Approved compiled notes that now live under the managed wiki root.")}</section>'
    )
    return _page(
        title="Library",
        active="library",
        eyebrow="Library",
        heading="Library",
        summary="Inspect the compiled notes that have already been approved and written into the Synapse-managed wiki subtree.",
        body=body,
    )


def render_operations_page(
    *,
    managed_root: str,
    vault_root: str,
    counts: dict[str, int],
    recent_proposals: Iterable[dict[str, Any]],
    log_entries: Iterable[dict[str, str]],
    artifacts: dict[str, str],
) -> str:
    activity = []
    for entry in log_entries:
        activity.append(
            f"<strong>{escape(entry.get('timestamp') or '-')}</strong>"
            f"<span class=\"small\">{escape(entry.get('message') or '')}</span>"
        )
    proposal_table = (
        "<table><thead><tr>"
        "<th>ID</th><th>Kind</th><th>Title</th><th>Status</th><th>Source</th><th>Target</th>"
        "</tr></thead><tbody>"
        f"{_render_proposal_rows(recent_proposals, empty_text='No proposal activity recorded.')}"
        "</tbody></table>"
    )
    body = (
        '<section class="section split">'
        f"{_panel('Runtime surface', ''.join((
            '<dl class=\"kv\">',
            '<dt>Vault root</dt><dd><code>' + escape(vault_root) + '</code></dd>',
            '<dt>Managed root</dt><dd><code>' + escape(managed_root) + '</code></dd>',
            '<dt>Index artifact</dt><dd><code>' + escape(artifacts.get('index_path', '-')) + '</code></dd>',
            '<dt>Log artifact</dt><dd><code>' + escape(artifacts.get('log_path', '-')) + '</code></dd>',
            '</dl>',
        )))}"
        f"{_panel('Status distribution', ''.join((
            '<div class=\"cards\">',
            ''.join(_metric(status.title(), value, 'Current proposal count') for status, value in sorted(counts.items())),
            '</div>',
        )))}"
        "</section>"
        '<section class="section split">'
        f"{_panel('Operational activity', _activity_list(activity, empty='No operational log entries yet.'), subtitle='Recent apply and reject events from the managed log.')}"
        f"{_panel('What to inspect next', _activity_list([
            'Use <a href=\"/ui/knowledge/proposals\">Review</a> for pending proposals.',
            'Use <a href=\"/ui/knowledge/library\">Library</a> to inspect approved notes.',
            'Use <a href=\"/ui/knowledge/logs\">Logs</a> for the raw append-only operational trail.',
        ], empty='No follow-up steps.'))}"
        "</section>"
        f'<section class="section">{_panel("Recent proposal activity", proposal_table)}</section>'
    )
    return _page(
        title="Operations",
        active="operations",
        eyebrow="Operations",
        heading="Operations",
        summary="Monitor the managed knowledge pipeline as an operator: artifacts, status distribution, and the recent activity that explains what changed.",
        body=body,
    )


def render_logs_page(
    *,
    log_path: str,
    log_entries: Iterable[dict[str, str]],
    raw_log: str,
) -> str:
    entry_rows = []
    for entry in log_entries:
        entry_rows.append(
            "<tr>"
            f"<td>{escape(entry.get('timestamp') or '-')}</td>"
            f"<td>{escape(entry.get('message') or '')}</td>"
            "</tr>"
        )
    if not entry_rows:
        entry_rows.append('<tr><td colspan="2" class="empty">No log entries yet.</td></tr>')
    parsed = (
        "<table><thead><tr><th>Timestamp</th><th>Event</th></tr></thead><tbody>"
        + "".join(entry_rows)
        + "</tbody></table>"
    )
    body = (
        f'<section class="section">{_panel("Append-only operational log", parsed, subtitle="A lightweight audit trail of apply and reject actions stored under the managed root.")}</section>'
        f'<section class="section">{_panel("Raw log file", "<div class=\"raw-box\"><pre>" + escape(raw_log or "(log file not created yet)") + "</pre></div>", subtitle="Path: " + log_path)}</section>'
    )
    return _page(
        title="Logs",
        active="logs",
        eyebrow="Logs",
        heading="Logs",
        summary="Inspect the append-only operational trail that explains how proposals moved through the built-in knowledge workflow.",
        body=body,
    )
