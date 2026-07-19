import os
import json
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Scopes required for uploading YouTube videos
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def main():
    print("=== YouTube OAuth Refresh Token Generator ===")
    print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
    print("2. Create a new project or select an existing one.")
    print("3. Enable the 'YouTube Data API v3'.")
    print("4. Go to 'Credentials' -> 'Create Credentials' -> 'OAuth client ID'.")
    print("   (Choose 'Desktop App' as the application type).")
    print("5. Download the JSON file and save it in this folder as 'client_secret.json'.")
    print("==============================================\n")
    
    if not os.path.exists("client_secret.json"):
        print("ERROR: client_secret.json not found in the current directory.")
        return

    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing token...")
            creds.refresh(Request())
        else:
            print("Starting new OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                'client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())
            
    print("\nSUCCESS! Your token.json has been generated.")
    print("Please set the following environment variables in your .env file:\n")
    
    with open('client_secret.json', 'r') as f:
        client_data = json.load(f)
        client_id = client_data.get("installed", {}).get("client_id", "")
        client_secret = client_data.get("installed", {}).get("client_secret", "")
        
    with open('token.json', 'r') as f:
        token_data = json.load(f)
        refresh_token = token_data.get("refresh_token", "")
        
    print(f"YOUTUBE_CLIENT_ID={client_id}")
    print(f"YOUTUBE_CLIENT_SECRET={client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={refresh_token}")

if __name__ == '__main__':
    main()
