import os
import logging
import textwrap
import chess
import chess.svg
import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

def generate_thumbnail(fen: str, player: str, opponent: str, event: str, year: str, tactic: str, output_path: str) -> str:
    """
    Generate a 1080x1920 thumbnail for the chess shorts video using Pillow.
    """
    logger.info(f"Generating thumbnail for FEN: {fen}")
    
    # 1. Render board
    board = chess.Board(fen) if fen else chess.Board()
    svg_data = chess.svg.board(board=board, size=800)
    
    # Temporary save SVG as PNG
    os.makedirs("outputs", exist_ok=True)
    temp_png = os.path.join("outputs", "temp_thumb_board.png")
    
    doc = fitz.open(stream=svg_data.encode("utf-8"), filetype="svg")
    pix = doc[0].get_pixmap()
    pix.save(temp_png)
    
    # 2. Resize board to 800x800
    board_img = Image.open(temp_png).convert("RGBA")
    board_img = board_img.resize((800, 800), Image.Resampling.LANCZOS)
    
    # 3. Create 1080x1920 canvas with dark gradient
    thumb_w, thumb_h = 1080, 1920
    base_img = Image.new("RGBA", (thumb_w, thumb_h))
    draw = ImageDraw.Draw(base_img)
    
    c1 = (26, 26, 46)  # #1a1a2e
    c2 = (22, 33, 62)  # #16213e
    for y in range(thumb_h):
        r = int(c1[0] + (c2[0] - c1[0]) * y / thumb_h)
        g = int(c1[1] + (c2[1] - c1[1]) * y / thumb_h)
        b = int(c1[2] + (c2[2] - c1[2]) * y / thumb_h)
        draw.line([(0, y), (thumb_w, y)], fill=(r, g, b))
        
    try:
        font_large = ImageFont.truetype("arialbd.ttf", 72)
        font_medium = ImageFont.truetype("arialbd.ttf", 52)
        font_small = ImageFont.truetype("arialbd.ttf", 40)
    except IOError:
        logger.warning("Arial font not found, falling back to default.")
        font_large = ImageFont.load_default()
        font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()
        
    # Draw Player Names at the very top
    vs_text = f"{player} vs {opponent}"
    wrapped_vs = textwrap.fill(vs_text, width=22)
    text_y = 100
    for line in wrapped_vs.split('\n'):
        bbox = draw.textbbox((0, 0), line, font=font_large)
        line_w = bbox[2] - bbox[0]
        draw.text(((thumb_w - line_w) // 2, text_y), line, font=font_large, fill="#FFD700") # Gold color
        text_y += (bbox[3] - bbox[1]) + 20
        
    # Draw Event and Year below names
    event_text = f"{event} {year}"
    bbox = draw.textbbox((0, 0), event_text, font=font_small)
    line_w = bbox[2] - bbox[0]
    draw.text(((thumb_w - line_w) // 2, text_y), event_text, font=font_small, fill="lightgray")
    
    # 4. Paste chess board
    board_x = (thumb_w - 800) // 2
    board_y = text_y + 80
    base_img.paste(board_img, (board_x, board_y), board_img)
    
    # 6. Add Tactic badge
    badge_text = tactic.upper() if tactic else "BRILLIANT MOVE"
    badge_color = (220, 53, 69) # Red
        
    bbox = draw.textbbox((0, 0), badge_text, font=font_medium)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    badge_x = (thumb_w - tw) // 2
    badge_y = board_y + 800 + 80
    pad_x, pad_y = 40, 20
    draw.rounded_rectangle(
        [badge_x - pad_x, badge_y - pad_y, badge_x + tw + pad_x, badge_y + th + pad_y], 
        radius=20, fill=badge_color
    )
    draw.text((badge_x, badge_y), badge_text, font=font_medium, fill="white")
    
    # 7. Add bottom text
    bottom_text = "Follow for daily chess puzzles \U0001F525"
    bbox = draw.textbbox((0, 0), bottom_text, font=font_medium)
    tw = bbox[2] - bbox[0]
    draw.text(((thumb_w - tw) // 2, thumb_h - 150), bottom_text, font=font_medium, fill="white")
    
    # 8. Output
    base_img = base_img.convert("RGB")
    base_img.save(output_path)
    
    logger.info(f"Thumbnail saved to {output_path}")
    return output_path

def generate_series_thumbnail(fen: str, number: int, rating: int, output_path: str) -> str:
    """Generate thumbnail for Puzzle Series format."""
    logger.info(f"Generating Series thumbnail for #{number}")
    board = chess.Board(fen) if fen else chess.Board()
    svg_data = chess.svg.board(board=board, size=700)
    
    os.makedirs("outputs", exist_ok=True)
    temp_png = os.path.join("outputs", f"temp_series_thumb_{number}.png")
    
    doc = fitz.open(stream=svg_data.encode("utf-8"), filetype="svg")
    pix = doc[0].get_pixmap()
    pix.save(temp_png)
    
    board_img = Image.open(temp_png).convert("RGBA")
    board_img = board_img.resize((700, 700), Image.Resampling.LANCZOS)
    
    thumb_w, thumb_h = 1080, 1920
    base_img = Image.new("RGBA", (thumb_w, thumb_h), (26, 0, 51)) # #1a0033
    draw = ImageDraw.Draw(base_img)
    
    # Border
    border_width = 8
    draw.rectangle([0, 0, thumb_w, thumb_h], outline="#9C27B0", width=border_width)
    
    try:
        font_huge = ImageFont.truetype("arialbd.ttf", 160)
        font_large = ImageFont.truetype("arialbd.ttf", 90)
        font_medium = ImageFont.truetype("arialbd.ttf", 60)
    except:
        font_huge = font_large = font_medium = ImageFont.load_default()
        
    # Big Number
    num_text = f"#{number}"
    bbox = draw.textbbox((0, 0), num_text, font=font_huge)
    tw = bbox[2] - bbox[0]
    draw.text(((thumb_w - tw) // 2, 150), num_text, font=font_huge, fill="white")
    
    # Board
    board_x = (thumb_w - 700) // 2
    board_y = 450
    base_img.paste(board_img, (board_x, board_y), board_img)
    
    # Rating
    rating_text = f"⭐ {rating}"
    bbox = draw.textbbox((0, 0), rating_text, font=font_large)
    tw = bbox[2] - bbox[0]
    draw.text(((thumb_w - tw) // 2, board_y + 700 + 100), rating_text, font=font_large, fill="#FFD700")
    
    # Bottom text
    bottom_text = "Can you solve it?"
    bbox = draw.textbbox((0, 0), bottom_text, font=font_medium)
    tw = bbox[2] - bbox[0]
    draw.text(((thumb_w - tw) // 2, thumb_h - 250), bottom_text, font=font_medium, fill="white")
    
    base_img.convert("RGB").save(output_path, "PNG")
    if os.path.exists(temp_png):
        os.remove(temp_png)
    return output_path
