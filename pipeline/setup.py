import os
import httpx
import logging
import asyncio

logger = logging.getLogger(__name__)

async def setup_assets():
    """
    Downloads required assets (chess pieces, sounds) on startup.
    """
    logger.info("Checking and downloading assets...")
    pieces_dir = os.path.join("assets", "pieces", "cburnett")
    sounds_dir = os.path.join("assets", "sounds")
    fonts_dir = os.path.join("assets", "fonts")
    os.makedirs(pieces_dir, exist_ok=True)
    os.makedirs(sounds_dir, exist_ok=True)
    os.makedirs(fonts_dir, exist_ok=True)
    
    # Download pieces (using chess.com's neo piece set which has reliable PNGs)
    pieces = ["wP", "wN", "wB", "wR", "wQ", "wK", "bP", "bN", "bB", "bR", "bQ", "bK"]
    base_piece_url = "https://images.chesscomfiles.com/chess-themes/pieces/neo/150/{}.png"
    
    async with httpx.AsyncClient() as client:
        # Download font
        font_path = os.path.join(fonts_dir, "Inter-Bold.ttf")
        if not os.path.exists(font_path):
            logger.info("Downloading Inter-Bold font dynamically from Google Fonts...")
            try:
                import re
                api_url = "https://fonts.googleapis.com/css2?family=Inter:wght@700"
                # Android 4.3 UA triggers TrueType (.ttf) download instead of .woff2
                ua = "Mozilla/5.0 (Linux; U; Android 4.3; de-de; GT-I9300 Build/JSS15J) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30"
                resp = await client.get(api_url, headers={"User-Agent": ua})
                resp.raise_for_status()
                match = re.search(r"url\((https://[^)]+\.ttf)\)", resp.text)
                if match:
                    font_url = match.group(1)
                    font_resp = await client.get(font_url)
                    font_resp.raise_for_status()
                    with open(font_path, "wb") as f:
                        f.write(font_resp.content)
                    logger.info("Font downloaded successfully.")
                else:
                    logger.warning("Could not find .ttf URL in Google Fonts CSS response.")
            except Exception as e:
                logger.warning(f"Failed to download Inter-Bold.ttf: {e}")

        for p in pieces:
            path = os.path.join(pieces_dir, f"{p}.png")
            if not os.path.exists(path):
                try:
                    # chess.com uses lowercase piece names (wp, wn, etc.)
                    resp = await client.get(base_piece_url.format(p.lower()))
                    resp.raise_for_status()
                    with open(path, "wb") as f:
                        f.write(resp.content)
                except Exception as e:
                    logger.warning(f"Failed to download piece {p}: {e}")
                    
        # Download move sound
        sound_path = os.path.join(sounds_dir, "move.mp3")
        if not os.path.exists(sound_path):
            try:
                # Use a reliable URL for a generic move sound (lichess move sound)
                resp = await client.get("https://raw.githubusercontent.com/lichess-org/lila/master/public/sound/standard/Move.mp3")
                resp.raise_for_status()
                with open(sound_path, "wb") as f:
                    f.write(resp.content)
            except Exception as e:
                logger.warning(f"Failed to download move sound: {e}")
                
    logger.info("Assets ready.")
