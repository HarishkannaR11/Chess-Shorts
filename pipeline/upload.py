import os
import json
import time
import logging
import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly"
]

# Transient server errors worth retrying during a resumable upload
RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_UPLOAD_RETRIES = 5

def _clean_text(text: str, max_bytes: int) -> str:
    """YouTube rejects '<' and '>' in titles/descriptions and enforces byte limits."""
    text = (text or "").replace("<", "").replace(">", "").strip()
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore").strip()

def _clean_tags(tags: list) -> list:
    """Dedupe tags and keep them under YouTube's 500-character total."""
    cleaned, seen, total = [], set(), 0
    for tag in tags:
        tag = str(tag).replace("<", "").replace(">", "").replace(",", " ").strip().lstrip("#").strip()
        if not tag or tag.lower() in seen:
            continue
        # YouTube counts quotes around tags containing spaces, plus separators
        cost = len(tag) + (2 if " " in tag else 0) + (1 if cleaned else 0)
        if total + cost > 500:
            break
        cleaned.append(tag)
        seen.add(tag.lower())
        total += cost
    return cleaned

def get_authenticated_service():
    creds = None
    
    # Check for direct environment variables (AWS Production mode)
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    
    if client_id and client_secret and refresh_token:
        logger.info("Using YouTube OAuth credentials from environment variables.")
        # No `scopes` here on purpose: Google rejects a refresh that asks for
        # scopes the token wasn't granted (invalid_scope). Leaving them out
        # returns whatever the token was minted with.
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        # When env credentials are set we're usually headless (server/CI), so
        # fail loudly instead of falling through to the interactive browser flow.
        try:
            creds.refresh(Request())
        except Exception as e:
            raise RuntimeError(
                "YouTube refresh token was rejected. Re-run `python youtube_auth.py` and update "
                "YOUTUBE_REFRESH_TOKEN. If this keeps happening every ~7 days, publish your OAuth "
                f"consent screen ('In production') in Google Cloud Console. Details: {e}"
            ) from e
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    if os.environ.get("GITHUB_ACTIONS"):
        # A CI runner has no token files or browser: the secrets are the only way in
        missing = [n for n, v in (("YOUTUBE_CLIENT_ID", client_id), ("YOUTUBE_CLIENT_SECRET", client_secret),
                                  ("YOUTUBE_REFRESH_TOKEN", refresh_token)) if not v]
        raise RuntimeError(
            f"Missing GitHub secret(s): {', '.join(missing)}. Add them in the repo under Settings > "
            "Secrets and variables > Actions (values come from `python youtube_auth.py`)."
        )

    # Fallback to local files
    logger.info("Environment credentials not found or invalid. Falling back to local files.")
    token_path = os.path.join("outputs", "token.json")
    client_secret_path = os.environ.get("YOUTUBE_CLIENT_SECRET_PATH", "credentials.json")
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                raise FileNotFoundError(f"OAuth credentials not found at {client_secret_path}. Please set YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN in .env or provide {client_secret_path}")
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
            
        os.makedirs("outputs", exist_ok=True)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
            
    return build("youtube", "v3", credentials=creds)

def authenticate():
    """Helper function to run the OAuth flow manually from terminal."""
    get_authenticated_service()
    print("Authentication successful! token.json has been saved in outputs/")

def upload_to_youtube(video_path: str, thumbnail_path: str, title: str, description: str, tags: list, privacy: str = "public") -> tuple:
    """
    Uploads a video to YouTube and sets its thumbnail.
    Returns: (youtube_url, video_id)
    """
    logger.info(f"Starting YouTube upload for {video_path}")
    try:
        youtube = get_authenticated_service()
        
        # Ensure essential tags are present
        tags = _clean_tags(list(tags) + ["shorts", "chess", "tactics"])
            
        # Append tags as visible hashtags in description
        description = description or ""
        hashtag_string = " ".join([f"#{t.replace(' ', '')}" for t in tags if t])
        if hashtag_string not in description:
            description += f"\n\n{hashtag_string}"

        title = _clean_text(title, 100) or "Chess Puzzle"
        description = _clean_text(description, 5000)
            
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "17"  # Sports
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False
            }
        }
        
        logger.info(f"--- YOUTUBE UPLOAD PAYLOAD ---")
        logger.info(json.dumps(body, indent=2))
        logger.info(f"------------------------------")
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        retries = 0
        while response is None:
            try:
                status, response = request.next_chunk()
            except (HttpError, OSError, httplib2.HttpLib2Error) as e:
                if isinstance(e, HttpError) and e.resp.status not in RETRIABLE_STATUS:
                    raise
                retries += 1
                if retries > MAX_UPLOAD_RETRIES:
                    raise
                wait = 2 ** retries
                logger.warning(f"Upload interrupted ({e}); retrying in {wait}s ({retries}/{MAX_UPLOAD_RETRIES})")
                time.sleep(wait)
                continue
            if status:
                logger.info(f"Uploaded {int(status.progress() * 100)}%")
                
        video_id = response.get("id")
        logger.info(f"Video uploaded successfully. Video ID: {video_id}")
        
        if thumbnail_path and os.path.exists(thumbnail_path):
            logger.info("Uploading thumbnail...")
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path)
                ).execute()
                logger.info("Thumbnail set successfully.")
            except Exception as thumb_e:
                logger.warning(f"Could not set custom thumbnail (channel might not be phone-verified or Shorts thumbnails unsupported): {thumb_e}")
            
        youtube_url = f"https://youtu.be/{video_id}"
        return youtube_url, video_id
        
    except Exception as e:
        logger.error(f"Error uploading to YouTube: {e}")
        raise
