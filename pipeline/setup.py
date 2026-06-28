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
    os.makedirs(pieces_dir, exist_ok=True)
    os.makedirs(sounds_dir, exist_ok=True)
    
    # Download pieces (using chess.com's neo piece set which has reliable PNGs)
    pieces = ["wP", "wN", "wB", "wR", "wQ", "wK", "bP", "bN", "bB", "bR", "bQ", "bK"]
    base_piece_url = "https://images.chesscomfiles.com/chess-themes/pieces/neo/150/{}.png"
    
    async with httpx.AsyncClient() as client:
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
