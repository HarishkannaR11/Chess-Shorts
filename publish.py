"""
Generate one chess Short and publish it to YouTube.

Entrypoint for unattended runs (GitHub Actions, cron, Docker):

    python publish.py                     # next format in the rotation, public
    python publish.py --format story      # pick the format yourself
    python publish.py --privacy unlisted  # or set YOUTUBE_PRIVACY
    python publish.py --no-upload         # dry run: render + QA only
    python publish.py --force             # ignore the once-a-day guard

Exits non-zero on failure so the scheduler flags the run.
"""
import os
import sys
import json
import asyncio
import logging
import argparse
from dotenv import load_dotenv

load_dotenv()

from pipeline.daily import publish_daily, FORMATS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("publish")


def write_summary(summary: dict):
    """Leave a machine-readable record, plus a GitHub Actions job summary when available."""
    os.makedirs("outputs", exist_ok=True)
    with open(os.path.join("outputs", "last_run.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not step_summary:
        return
    lines = ["## Daily Short", ""]
    for key in ("status", "format", "title", "youtube_url", "privacy", "reason", "error"):
        if summary.get(key):
            lines.append(f"- **{key}**: {summary[key]}")
    with open(step_summary, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", choices=FORMATS + ["auto"], default="auto",
                        help="format to generate (default: next in rotation)")
    parser.add_argument("--privacy", choices=["public", "unlisted", "private"],
                        default=os.environ.get("YOUTUBE_PRIVACY") or "public")
    parser.add_argument("--no-upload", action="store_true", help="render and QA only")
    parser.add_argument("--force", action="store_true", help="publish even if one went out in the last 20h")
    args = parser.parse_args()

    try:
        summary = asyncio.run(publish_daily(
            fmt=None if args.format == "auto" else args.format,
            upload=not args.no_upload,
            privacy=args.privacy,
            force=args.force,
        ))
    except Exception as e:
        logger.exception("Daily publish failed")
        write_summary({"status": "failed", "error": str(e)})
        sys.exit(1)

    write_summary(summary)
    logger.info(f"Done: {json.dumps(summary)}")


if __name__ == "__main__":
    main()
