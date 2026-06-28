import os
import logging
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_authenticated_service():
    creds = None
    token_path = os.path.join("outputs", "token.json")
    client_secret_path = os.environ.get("YOUTUBE_CLIENT_SECRET_PATH", "credentials.json")
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                raise FileNotFoundError(f"OAuth credentials not found at {client_secret_path}")
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

def upload_to_youtube(video_path: str, thumbnail_path: str, title: str, description: str, tags: list) -> tuple:
    """
    Uploads a video to YouTube and sets its thumbnail.
    Returns: (youtube_url, video_id)
    """
    logger.info(f"Starting YouTube upload for {video_path}")
    try:
        youtube = get_authenticated_service()
        
        if "#shorts" not in description.lower():
            description += "\n\n#shorts #chess #tactics"
            
        if "shorts" not in [t.lower() for t in tags]:
            tags.append("shorts")
            
        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags,
                "categoryId": "17"  # Sports
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }
        
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media
        )
        
        response = None
        while response is None:
            status, response = request.next_chunk()
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
