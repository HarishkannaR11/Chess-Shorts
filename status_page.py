"""
Build the public status page for the daily Shorts automation.

    python status_page.py --out site

Reads the SQLite database and outputs/last_run.json (written by publish.py)
and writes site/index.html + site/status.json. Standard library only, so it
still runs when a publish run failed early. The Daily Short workflow deploys
the result to GitHub Pages after every run.
"""
import os
import re
import json
import html
import sqlite3
import argparse
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join("database", "chess_shorts.db")
LAST_RUN_PATH = os.path.join("outputs", "last_run.json")
WORKFLOW_PATH = os.path.join(".github", "workflows", "daily-short.yml")
FORMATS = ["flash", "story", "series"]


def _parse_utc(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fmt_date(dt, with_time=False) -> str:
    if not dt:
        return ""
    text = f"{dt:%b} {dt.day}, {dt.year}"
    return f"{text} · {dt:%H:%M} UTC" if with_time else text


def next_scheduled_run(now: datetime):
    """Next run from a daily 'M H * * *' cron in the workflow; None if it's not that simple."""
    try:
        with open(WORKFLOW_PATH, encoding="utf-8") as f:
            match = re.search(r'cron:\s*"(\d+) (\d+) \* \* \*"', f.read())
    except OSError:
        return None
    if not match:
        return None
    minute, hour = int(match.group(1)), int(match.group(2))
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def load_data(now: datetime) -> dict:
    data = {"videos": [], "published": 0, "last_7_days": 0, "next_format": "flash", "next_series": 1}
    if not os.path.exists(DB_PATH):
        return data
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        columns = {r[1] for r in con.execute("PRAGMA table_info(videos)")}
        uploaded_at = "uploaded_at" if "uploaded_at" in columns else "NULL"
        rows = con.execute(
            f"SELECT title, format, status, youtube_url, created_at, {uploaded_at} AS uploaded_at "
            "FROM videos ORDER BY id DESC LIMIT 30"
        ).fetchall()
        data["videos"] = [dict(r) for r in rows]
        data["published"] = con.execute("SELECT COUNT(*) FROM videos WHERE status = 'uploaded'").fetchone()[0]
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        data["last_7_days"] = con.execute(
            f"SELECT COUNT(*) FROM videos WHERE status = 'uploaded' AND {uploaded_at} >= ?", (week_ago,)
        ).fetchone()[0]
        # Same rotation rule as pipeline/daily.py
        last = con.execute("SELECT format FROM used_content ORDER BY created_at DESC LIMIT 1").fetchone()
        if last:
            data["next_format"] = {"flash": "story", "story": "series"}.get(last[0], "flash")
        top = con.execute("SELECT MAX(puzzle_number) FROM puzzle_series").fetchone()[0]
        data["next_series"] = (top or 0) + 1
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return data


def load_last_run() -> dict:
    try:
        with open(LAST_RUN_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def describe_run(run: dict):
    """(tone, headline, detail) for the last-run banner."""
    status = run.get("status")
    title = html.escape(run.get("title") or "")
    url = run.get("youtube_url")
    if status == "uploaded":
        link = f'<a href="{html.escape(url)}">{title}</a>' if url else title
        return "ok", "Published today's Short", f"{link} ({html.escape(run.get('format', ''))}, {html.escape(run.get('privacy', 'public'))})"
    if status == "skipped":
        return "neutral", "Skipped: already published", html.escape(run.get("reason", ""))
    if status == "generated":
        return "neutral", "Dry run: rendered, not uploaded", title
    if status == "failed":
        return "fail", "Last run failed", html.escape((run.get("error") or "")[:400])
    return "fail", "Last run didn't finish", "Open the run log for details."


def render(data: dict, run: dict, now: datetime, repo: str, run_url: str) -> str:
    tone, headline, detail = describe_run(run)
    next_run = next_scheduled_run(now)
    actions_url = f"https://github.com/{repo}/actions/workflows/daily-short.yml" if repo else "#"

    items = []
    for v in data["videos"]:
        when = _parse_utc(v.get("uploaded_at")) or _parse_utc(v.get("created_at"))
        title = html.escape(v.get("title") or "Untitled")
        if v.get("youtube_url"):
            title = f'<a href="{html.escape(v["youtube_url"])}">{title}</a>'
        fmt = v.get("format") or "story"
        state = "Published" if v.get("status") == "uploaded" else "Not uploaded"
        items.append(
            f'<li><span class="badge {html.escape(fmt)}">{html.escape(fmt.capitalize())}</span>'
            f'<div class="item"><span class="item-title">{title}</span>'
            f'<span class="meta">{_fmt_date(when)}</span></div>'
            f'<span class="state {"done" if state == "Published" else "todo"}">{state}</span></li>'
        )
    videos_html = "\n".join(items) or '<li class="empty">No Shorts yet. The first one goes out on the next run.</li>'
    run_link = f' · <a href="{html.escape(run_url)}">View run</a>' if run_url else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knightify Daily Shorts</title>
<meta name="description" content="Status of the Knightify Chess daily YouTube Shorts automation.">
<style>
:root {{
  --bg: #f6f5f2; --surface: #ffffff; --text: #1c1b19; --muted: #6b675f; --line: #e4e1da;
  --accent: #7a4fd6; --ok: #1f8a4c; --ok-bg: #e6f4ec; --fail: #c0392b; --fail-bg: #fbe9e7;
  --neutral: #8a6d1d; --neutral-bg: #fbf3dc;
  --flash: #d9480f; --story: #7a4fd6; --series: #1971c2;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #141312; --surface: #1d1c1a; --text: #f0eee9; --muted: #a29d93; --line: #2f2d29;
    --accent: #a98bf0; --ok: #5fcf8d; --ok-bg: #16301f; --fail: #f08a7e; --fail-bg: #3a1b17;
    --neutral: #e3c46a; --neutral-bg: #332a12;
    --flash: #ff8a4c; --story: #a98bf0; --series: #6cb4f5;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 32px 16px 48px; }}
a {{ color: var(--accent); }}
header {{ display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
.eyebrow {{ margin: 0; color: var(--muted); font-size: 13px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; }}
h1 {{ margin: 2px 0 0; font-size: 30px; line-height: 1.15; }}
h2 {{ font-size: 18px; margin: 32px 0 12px; }}
.btn {{ display: inline-block; padding: 8px 14px; border: 1px solid var(--line); border-radius: 8px;
  background: var(--surface); color: var(--text); text-decoration: none; font-weight: 600; font-size: 14px; }}
.btn:hover {{ border-color: var(--accent); }}
.banner {{ display: flex; gap: 12px; padding: 16px; border-radius: 12px; background: var(--surface); border: 1px solid var(--line); }}
.banner .dot {{ flex: none; width: 12px; height: 12px; margin-top: 6px; border-radius: 50%; }}
.banner.ok {{ background: var(--ok-bg); }} .banner.ok .dot {{ background: var(--ok); }}
.banner.fail {{ background: var(--fail-bg); }} .banner.fail .dot {{ background: var(--fail); }}
.banner.neutral {{ background: var(--neutral-bg); }} .banner.neutral .dot {{ background: var(--neutral); }}
.banner strong {{ display: block; }}
.banner p {{ margin: 2px 0 0; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 16px; }}
.stat {{ background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }}
.stat .label {{ display: block; color: var(--muted); font-size: 13px; }}
.stat .value {{ display: block; font-size: 20px; font-weight: 700; margin-top: 2px; }}
ol {{ list-style: none; margin: 0; padding: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; }}
li {{ display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-top: 1px solid var(--line); }}
li:first-child {{ border-top: 0; }}
li.empty {{ color: var(--muted); }}
.badge {{ flex: none; width: 64px; text-align: center; font-size: 12px; font-weight: 700; padding: 3px 0; border-radius: 999px;
  color: var(--story); border: 1px solid currentColor; }}
.badge.flash {{ color: var(--flash); }} .badge.series {{ color: var(--series); }}
.item {{ flex: 1; min-width: 0; }}
.item-title {{ display: block; font-weight: 600; overflow-wrap: anywhere; }}
.item-title a {{ color: var(--text); }}
.meta {{ color: var(--muted); font-size: 13px; }}
.state {{ flex: none; font-size: 13px; color: var(--muted); }}
.state.done {{ color: var(--ok); font-weight: 600; }}
footer {{ margin-top: 24px; color: var(--muted); font-size: 13px; }}
@media (max-width: 560px) {{
  .stats {{ grid-template-columns: repeat(2, 1fr); }}
  li {{ flex-wrap: wrap; row-gap: 6px; }}
  .item {{ order: 3; flex-basis: 100%; }}
  .state {{ margin-left: auto; }}
}}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <p class="eyebrow">Knightify Chess</p>
      <h1>Daily Shorts</h1>
    </div>
    <a class="btn" href="{actions_url}">Run history &amp; manual run</a>
  </header>

  <section class="banner {tone}" aria-live="polite">
    <span class="dot" aria-hidden="true"></span>
    <div>
      <strong>{headline}</strong>
      <p>{detail}</p>
      <p>{_fmt_date(now, with_time=True)}{run_link}</p>
    </div>
  </section>

  <section class="stats">
    <div class="stat"><span class="label">Published</span><span class="value">{data["published"]}</span></div>
    <div class="stat"><span class="label">Last 7 days</span><span class="value">{data["last_7_days"]}</span></div>
    <div class="stat"><span class="label">Next run</span><span class="value">{f"{next_run:%b} {next_run.day}, {next_run:%H:%M} UTC" if next_run else "See workflow"}</span></div>
    <div class="stat"><span class="label">Next format</span><span class="value">{data["next_format"].capitalize()}</span></div>
  </section>

  <h2>Recent Shorts</h2>
  <ol>
{videos_html}
  </ol>

  <footer>Next Series puzzle: #{data["next_series"]}. Updated {_fmt_date(now, with_time=True)} by the Daily Short workflow.</footer>
</main>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build the daily Shorts status page.")
    parser.add_argument("--out", default="site", help="output directory (default: site)")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    data = load_data(now)
    run = load_last_run()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = ""
    if repo and os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(render(data, run, now, repo, run_url))
    with open(os.path.join(args.out, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"updated": now.isoformat(), "last_run": run, **data}, f, indent=2, default=str)
    print(f"Status page written to {args.out}/index.html")


if __name__ == "__main__":
    main()
