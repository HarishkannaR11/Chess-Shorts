import os
import logging
from datetime import datetime
import aiosqlite
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from database.db import DB_PATH

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly"
]

def get_analytics_service():
    token_path = os.path.join("outputs", "token.json")
    if not os.path.exists(token_path):
        logger.warning(f"No token.json found at {token_path}, cannot fetch analytics.")
        return None
    try:
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w") as token_file:
                token_file.write(creds.to_json())
        return build("youtubeAnalytics", "v2", credentials=creds)
    except Exception as e:
        logger.error(f"Failed to build YouTube Analytics service: {e}")
        return None

async def sync_all_uploaded_analytics():
    """Queries analytics for all uploaded videos from their upload date to today."""
    youtube_analytics = get_analytics_service()
    if not youtube_analytics:
        return {"success": False, "error": "Analytics token or service not available."}
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT video_id, created_at FROM videos WHERE status = 'uploaded'") as cursor:
            uploaded_videos = await cursor.fetchall()
            
    success_count = 0
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    
    for video in uploaded_videos:
        video_id = video["video_id"]
        created_at = video["created_at"]
        if not video_id:
            continue
            
        # Extract date component YYYY-MM-DD from created_at
        try:
            # Handle formats like '2026-07-19 14:30:57' or ISO formats
            start_date = created_at.split()[0] if " " in created_at else created_at.split("T")[0]
        except Exception:
            start_date = "2026-01-01"
            
        try:
            logger.info(f"Querying analytics for video {video_id} starting from {start_date}")
            # Query standard views & averageViewPercentage (retention proxy)
            result = youtube_analytics.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=today_str,
                metrics="views,averageViewPercentage",
                dimensions="video",
                filters=f"video=={video_id}"
            ).execute()

            rows = result.get("rows", [])
            if rows:
                views = int(rows[0][1])
                viewed_pct = float(rows[0][2]) if rows[0][2] is not None else 0.0
                
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE videos SET views = ?, viewed_percentage = ? WHERE video_id = ?",
                        (views, viewed_pct, video_id)
                    )
                    await db.commit()
                logger.info(f"Synced video {video_id}: {views} views, {viewed_pct}% viewed_percentage")
                success_count += 1
            else:
                logger.info(f"No analytics rows returned for video {video_id} (too new or no views).")
        except Exception as e:
            logger.error(f"Error syncing video {video_id}: {e}")
            
    return {"success": True, "synced_count": success_count}
