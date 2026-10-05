import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

from pipeline.upload import SCOPES

SECRET_FILES = ["client_secret.json", "credentials.json"]

def main():
    print("=== YouTube OAuth Refresh Token Generator ===")
    print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
    print("2. Create a new project or select an existing one.")
    print("3. Enable the 'YouTube Data API v3'.")
    print("4. Go to 'Credentials' -> 'Create Credentials' -> 'OAuth client ID'.")
    print("   (Choose 'Desktop App' as the application type).")
    print("5. Download the JSON file and save it in this folder as 'client_secret.json'.")
    print("==============================================\n")

    secrets_path = next((p for p in SECRET_FILES if os.path.exists(p)), None)
    if not secrets_path:
        print(f"ERROR: none of {', '.join(SECRET_FILES)} found in the current directory.")
        return

    # Always run a fresh consent: offline + consent guarantees Google returns a
    # refresh token, and it is minted with every scope the app uses.
    print("Starting OAuth flow in your browser...")
    flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())

    with open(secrets_path, 'r') as f:
        client_data = json.load(f)
    client_info = client_data.get("installed") or client_data.get("web") or {}

    print("\nSUCCESS! Your token.json has been generated.")
    print("Set these in your .env file (local/VM) or as GitHub Actions secrets:\n")
    print(f"YOUTUBE_CLIENT_ID={client_info.get('client_id', '')}")
    print(f"YOUTUBE_CLIENT_SECRET={client_info.get('client_secret', '')}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("\nNOTE: if your OAuth consent screen is still in 'Testing', Google expires this")
    print("refresh token after 7 days. Set it to 'In production' for unattended uploads.")

if __name__ == '__main__':
    main()
