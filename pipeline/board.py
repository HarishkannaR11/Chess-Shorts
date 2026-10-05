import os
import logging
import chess
from PIL import Image, ImageDraw, ImageFont
from typing import List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

PIECE_MAP = {
    'P': 'wP', 'N': 'wN', 'B': 'wB', 'R': 'wR', 'Q': 'wQ', 'K': 'wK',
    'p': 'bP', 'n': 'bN', 'b': 'bB', 'r': 'bR', 'q': 'bQ', 'k': 'bK'
}
PIECE_SYMBOLS = {
    'P': '\u2659', 'N': '\u2658', 'B': '\u2657', 'R': '\u2656', 'Q': '\u2655', 'K': '\u2654',
    'p': '\u265F', 'n': '\u265E', 'b': '\u265D', 'r': '\u265C', 'q': '\u265B', 'k': '\u265A'
}

PIECE_IMAGE_CACHE = {}
UNICODE_FONT = None

def get_unicode_font():
    global UNICODE_FONT
    if UNICODE_FONT is None:
        try:
            if os.name == 'nt':
                font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\seguisym.ttf'
                if not os.path.exists(font_path):
                    font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\arial.ttf'
                UNICODE_FONT = ImageFont.truetype(font_path, 80)
            else:
                UNICODE_FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 80)
        except Exception:
            UNICODE_FONT = ImageFont.load_default()
    return UNICODE_FONT

def get_text_font(size=20):
    try:
        font_path = "assets/fonts/Inter-Bold.ttf"
        if os.path.exists(font_path):
            return ImageFont.truetype(font_path, size)
        if os.name == 'nt':
            font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\arialbd.ttf'
            return ImageFont.truetype(font_path, size)
        else:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()

def load_all_fonts():
    sizes = [18, 20, 28, 30, 34, 35, 36, 40, 44, 48, 50, 52, 56, 80, 110]
    return {sz: get_text_font(sz) for sz in sizes}

def get_text_width(draw, text, font):
    """Fallback-safe text measurement across PIL versions."""
    try:
        return draw.textlength(text, font=font)
    except AttributeError:
        try:
            return draw.textbbox((0, 0), text, font=font)[2]
        except AttributeError:
            return font.getsize(text)[0]

def draw_caption(draw, text, t, t_start, t_end, font, center_x, center_y):
    """Draws a moving 5-word sentence window, highlighting the active spoken word in yellow."""
    words = text.split()
    if not words:
        return
    dur = t_end - t_start
    word_dur = dur / len(words)
    active_idx = int((t - t_start) / word_dur)
    active_idx = max(0, min(len(words) - 1, active_idx))
    
    # 5-word sliding window centered on active word
    window_sz = 5
    start_w = max(0, active_idx - 2)
    end_w = min(len(words), start_w + window_sz)
    if end_w - start_w < window_sz:
        start_w = max(0, end_w - window_sz)
        
    window_words = words[start_w:end_w]
    rel_active_idx = active_idx - start_w
    
    space_w = get_text_width(draw, " ", font)
    word_widths = [get_text_width(draw, w, font) for w in window_words]
    total_w = sum(word_widths) + space_w * (len(window_words) - 1)
    
    start_x = center_x - total_w / 2
    cur_x = start_x
    for idx, w in enumerate(window_words):
        color = (255, 215, 0, 255) if idx == rel_active_idx else (255, 255, 255, 255)
        # Drop shadow
        draw.text((cur_x + 2, center_y + 2), w, font=font, fill=(0, 0, 0, 255))
        # Word text
        draw.text((cur_x, center_y), w, font=font, fill=color)
        cur_x += word_widths[idx] + space_w

def pad_to_vertical(board_img: Image.Image, format_type: str, t: float, extra: dict) -> Image.Image:
    """Composites the 1080x1080 board into a 1080x1920 layout and draws all UI overlays."""
    
    bgs = extra.get("bgs", [])
    if bgs:
        section_idx = 0
        section_start = 0.0
        section_times = extra.get("section_times", [])
        
        if section_times and format_type == "story":
            for idx, st in enumerate(section_times):
                if t >= st['start']:
                    section_idx = idx
                    section_start = st['start']
                else:
                    break
        else:
            section_idx = int(t // 4)
            section_start = section_idx * 4.0
            
        bg_img_src = bgs[section_idx % len(bgs)]
        progress = (t - section_start) / 5.0
        zoom = 1.0 - (0.1 * min(1.0, max(0.0, progress))) # zoom from 1.0 down to 0.9
        
        # Vary zoom direction per clip based on section_idx
        # Even: zoom in (1.0 -> 0.9). Odd: zoom out (0.9 -> 1.0)
        if section_idx % 2 != 0:
            zoom = 0.9 + (0.1 * min(1.0, max(0.0, progress)))
            
        w, h = bg_img_src.size
        cw, ch = w * zoom, h * zoom
        left = (w - cw) / 2
        top = (h - ch) / 2
        
        bg_cropped = bg_img_src.crop((left, top, left + cw, top + ch))
        img = bg_cropped.resize((1080, 1920), Image.Resampling.LANCZOS)
    else:
        img = Image.new('RGBA', (1080, 1920), (13, 13, 13, 255)) # Dark background

    draw = ImageDraw.Draw(img)
    
    # Paste board in the center
    img.paste(board_img, (0, 280))
    
    fonts = extra.get("fonts")
    def get_font(size):
        if fonts and size in fonts:
            return fonts[size]
        return get_text_font(size)
        
    rating = extra.get("rating", 1500)
    themes = extra.get("themes", [])
    sol_moves = extra.get("sol_moves", [])
    cta_text = extra.get("cta_text", "Comment your move before I show mine!")
    
    is_mate = any("mate" in str(th).lower() for th in themes) if themes else True
    moves_count = len(sol_moves) // 2 if sol_moves else 2
    if moves_count == 0:
        moves_count = 2
        
    if is_mate:
        stakes_text = f"Mate in {moves_count} — can you find it?"
    else:
        stakes_text = f"Win in {moves_count} moves — spot it!"
        
    # --- RENDER HEADER AREA (Top 280px) ---
    if format_type == "story":
        player = extra.get("player", "Player")
        opponent = extra.get("opponent", "Opponent")
        event = extra.get("event", "Event")
        year = extra.get("year", "2023")
        
        font_name = get_font(52)
        font_vs = get_font(36)
        font_event = get_font(34)
        font_pres = get_font(28)
        
        pres_str = "KNIGHTIFY CHESS PRESENTS"
        w_pres = get_text_width(draw, pres_str, font_pres)
        draw.text(((1080 - w_pres)/2, 30), pres_str, font=font_pres, fill=(170, 170, 170, 255))
        
        w1 = get_text_width(draw, player, font_name)
        draw.text(((1080 - w1)/2, 80), player, font=font_name, fill=(255, 215, 0, 255))
        
        wvs = get_text_width(draw, "vs", font_vs)
        draw.text(((1080 - wvs)/2, 140), "vs", font=font_vs, fill=(255, 255, 255, 255))
        
        w2 = get_text_width(draw, opponent, font_name)
        draw.text(((1080 - w2)/2, 180), opponent, font=font_name, fill=(255, 255, 255, 255))
        
        ev_str = f"{event} {year}"
        wev = get_text_width(draw, ev_str, font_event)
        draw.text(((1080 - wev)/2, 240), ev_str, font=font_event, fill=(170, 170, 170, 255))
        
    elif format_type == "series":
        number = extra.get("number", 1)
        font_title = get_font(36)
        font_num = get_font(110)
        font_star = get_font(30)
        
        draw.rectangle([0, 0, 1080, 220], fill=(33, 13, 77, 255))
        
        w_title = get_text_width(draw, "KNIGHTIFY CHESS PUZZLE", font_title)
        draw.text(((1080 - w_title)/2, 30), "KNIGHTIFY CHESS PUZZLE", font=font_title, fill=(170, 170, 170, 255))
        
        num_str = f"#{number}"
        w_num = get_text_width(draw, num_str, font_num)
        draw.text(((1080 - w_num)/2, 80), num_str, font=font_num, fill=(255, 255, 255, 255))
        
        star_str = f"⭐ {rating}"
        w_star = get_text_width(draw, star_str, font_star)
        draw.text((1080 - w_star - 40, 120), star_str, font=font_star, fill=(255, 255, 255, 255))
        
    elif format_type == "flash":
        hook = extra.get("hook", "Can YOU find the win? 🤔")
        font_hook = get_font(52)
        import textwrap
        lines = textwrap.wrap(hook, width=30)[:2]
        y_off = 80 if len(lines) == 1 else 50
        for line in lines:
            w_line = get_text_width(draw, line, font_hook)
            draw.text(((1080 - w_line)/2 + 2, y_off + 2), line, font=font_hook, fill=(0, 0, 0, 255))
            draw.text(((1080 - w_line)/2, y_off), line, font=font_hook, fill=(255, 255, 255, 255))
            y_off += 60
            
    # --- RENDER BOTTOM FOOTER AREA (y=1330 to 1920) ---
    total_duration = extra.get("duration", 30.0)
    
    # 1. Configurable End CTA Overlay (Final 2 seconds)
    if t >= (total_duration - 2.0):
        font_cta = get_font(48)
        w_cta = get_text_width(draw, cta_text, font_cta)
        draw.text(((1080 - w_cta)/2 + 2, 1550 + 2), cta_text, font=font_cta, fill=(0, 0, 0, 255))
        draw.text(((1080 - w_cta)/2, 1550), cta_text, font=font_cta, fill=(255, 215, 0, 255))
        
    # 2. Hook stakes text (0.0s to 3.0s)
    elif t <= 3.0:
        font_stakes = get_font(56)
        font_rate = get_font(44)
        
        w_stakes = get_text_width(draw, stakes_text, font_stakes)
        draw.text(((1080 - w_stakes)/2 + 2, 1450 + 2), stakes_text, font=font_stakes, fill=(0, 0, 0, 255))
        draw.text(((1080 - w_stakes)/2, 1450), stakes_text, font=font_stakes, fill=(255, 255, 255, 255))
        
        rate_str = f"⭐ Rating: {rating}"
        w_rate = get_text_width(draw, rate_str, font_rate)
        draw.text(((1080 - w_rate)/2, 1350), rate_str, font=font_rate, fill=(255, 215, 0, 255))
        
        if format_type == "series":
            font_count = get_font(80)
            count_str = ""
            if 1.0 <= t < 2.0: count_str = "3"
            elif 2.0 <= t < 2.6: count_str = "2"
            elif 2.6 <= t < 3.0: count_str = "1"
            if count_str:
                w_count = get_text_width(draw, count_str, font_count)
                draw.text(((1080 - w_count)/2, 1380), count_str, font=font_count, fill=(255, 255, 255, 255))
                
    # 3. Middle Main Phase
    else:
        if format_type == "story":
            section_times = extra.get("section_times", [])
            font_cap = get_font(52)
            # Find active word boundary
            for wb in section_times:
                if wb["start"] <= t < wb["end"]:
                    current_idx = section_times.index(wb)
                    start_w = max(0, current_idx - 2)
                    end_w = min(len(section_times), start_w + 5)
                    if end_w - start_w < 5:
                        start_w = max(0, end_w - 5)
                    window_wbs = section_times[start_w:end_w]
                    window_words = [item["word"] for item in window_wbs]
                    rel_active_idx = current_idx - start_w
                    
                    space_w = get_text_width(draw, " ", font_cap)
                    word_widths = [get_text_width(draw, w, font_cap) for w in window_words]
                    total_w = sum(word_widths) + space_w * (len(window_words) - 1)
                    
                    start_x = 540 - total_w / 2
                    cur_x = start_x
                    for idx, w in enumerate(window_words):
                        color = (255, 215, 0, 255) if idx == rel_active_idx else (255, 255, 255, 255)
                        draw.text((cur_x + 2, 1450 + 2), w, font=font_cap, fill=(0, 0, 0, 255))
                        draw.text((cur_x, 1450), w, font=font_cap, fill=color)
                        cur_x += word_widths[idx] + space_w
                    break
                    
        elif format_type == "series":
            theme = extra.get("theme", "Tactics").capitalize()
            difficulty = extra.get("difficulty", "Intermediate")
            font_green = get_font(52)
            font_diff = get_font(40)
            font_gray = get_font(35)
            
            if t > 5.0:
                theme_str = f"✓ {theme} tactic!"
                w_theme = get_text_width(draw, theme_str, font_green)
                draw.text(((1080 - w_theme)/2, 1400), theme_str, font=font_green, fill=(76, 175, 80, 255))
                
                diff_str = difficulty.upper()
                w_diff = get_text_width(draw, diff_str, font_diff)
                draw.text(((1080 - w_diff)/2, 1550), diff_str, font=font_diff, fill=(156, 39, 176, 255))
                
            footer_str = f"Follow Knightify Chess • #{extra.get('number', 1)}/∞"
            w_foot = get_text_width(draw, footer_str, font_gray)
            draw.text(((1080 - w_foot)/2, 1750), footer_str, font=font_gray, fill=(136, 136, 136, 255))
            
        elif format_type == "flash":
            font_rate = get_font(50)
            font_tags = get_font(40)
            
            rate_str = f"⭐ Rating: {rating}"
            w_rate = get_text_width(draw, rate_str, font_rate)
            draw.text(((1080 - w_rate)/2, 1350), rate_str, font=font_rate, fill=(255, 255, 255, 255))
            
            tags_str = "#tactics #puzzle #chess"
            w_tags = get_text_width(draw, tags_str, font_tags)
            draw.text(((1080 - w_tags)/2, 1450), tags_str, font=font_tags, fill=(170, 170, 170, 255))
            
            follow_str = "Follow Knightify Chess 🔥"
            w_fol = get_font(50)
            w_fol_w = get_text_width(draw, follow_str, w_fol)
            draw.text(((1080 - w_fol_w)/2 + 2, 1750 + 2), follow_str, font=w_fol, fill=(0, 0, 0, 255))
            draw.text(((1080 - w_fol_w)/2, 1750), follow_str, font=w_fol, fill=(255, 215, 0, 255))
            
    # Global watermark
    font_wm = get_font(30)
    wm_text = "@KnightifyChess"
    w_wm = get_text_width(draw, wm_text, font_wm)
    draw.text(((1080 - w_wm)/2, 1850), wm_text, font=font_wm, fill=(170, 170, 170, 180))
            
    return img.convert('RGB')

def _get_material_eval(board: chess.Board):
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    w = sum(values[p.piece_type] for p in board.piece_map().values() if p.color == chess.WHITE)
    b = sum(values[p.piece_type] for p in board.piece_map().values() if p.color == chess.BLACK)
    return w - b

def _draw_eval_bar(draw: ImageDraw, board: chess.Board, x_offset: int, y_offset: int, h: int, fonts: dict = None):
    eval_val = _get_material_eval(board)
    # limit eval between -10 and +10 for bar
    clamped = max(-10, min(10, eval_val))
    # map to percentage for white (bottom): +10 -> 1.0, 0 -> 0.5, -10 -> 0.0
    w_pct = 0.5 + (clamped / 20.0)
    w_height = int(h * w_pct)
    b_height = h - w_height
    
    # Black part (top)
    draw.rectangle([x_offset, y_offset, x_offset + 20, y_offset + b_height], fill=(40, 40, 40))
    # White part (bottom)
    draw.rectangle([x_offset, y_offset + b_height, x_offset + 20, y_offset + h], fill=(220, 220, 220))
    
    # Text
    txt_font = fonts[18] if (fonts and 18 in fonts) else get_text_font(18)
    sign = "+" if eval_val > 0 else ""
    txt = f"{sign}{eval_val}"
    # Draw text inside white part if white advantage, else in black part
    text_y = y_offset + h - 25 if eval_val > 0 else y_offset + 5
    text_col = "black" if eval_val > 0 else "white"
    draw.text((x_offset + 10, text_y), txt, font=txt_font, fill=text_col, anchor="mm")

def _get_square_rect(sq: int, board_x: int, board_y: int):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    x = board_x + file * 120
    y = board_y + (7 - rank) * 120
    return [x, y, x + 120, y + 120]

def _get_square_center(sq: int, board_x: int, board_y: int):
    file = chess.square_file(sq)
    rank = chess.square_rank(sq)
    x = board_x + file * 120 + 60
    y = board_y + (7 - rank) * 120 + 60
    return x, y

def _render_state(board: chess.Board, moving_piece=None, moving_pos=None, last_move=None, fonts: dict = None) -> Image.Image:
    # Canvas 1080x1080 black
    img = Image.new('RGBA', (1080, 1080), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    
    # Board metrics
    sq_sz = 120
    board_sz = 8 * sq_sz # 960
    border = 40
    total_sz = board_sz + 2 * border # 1040
    bx = (1080 - total_sz) // 2 + border # x offset of top-left square
    by = (1080 - total_sz) // 2 + border # y offset of top-left square
    
    # Border
    draw.rectangle([bx - border, by - border, bx + board_sz + border, by + board_sz + border], fill="#8B4513")
    
    # Coordinates
    font = fonts[20] if (fonts and 20 in fonts) else get_text_font(20)
    for i in range(8):
        # Letters a-h at bottom
        x = bx + i * sq_sz + sq_sz // 2
        y = by + board_sz + border // 2
        draw.text((x, y), chr(ord('a') + i), font=font, fill="white", anchor="mm")
        # Numbers 1-8 at left
        x = bx - border // 2
        y = by + (7 - i) * sq_sz + sq_sz // 2
        draw.text((x, y), str(i + 1), font=font, fill="white", anchor="mm")
        
    # Eval Bar (Left of border)
    _draw_eval_bar(draw, board, bx - border - 30, by, board_sz, fonts)
    
    # Squares
    colors = ['#F0D9B5', '#B58863']
    for sq in chess.SQUARES:
        file = chess.square_file(sq)
        rank = chess.square_rank(sq)
        color = colors[(rank + file) % 2]
        rect = _get_square_rect(sq, bx, by)
        draw.rectangle(rect, fill=color)
        
    # Highlights
    if last_move:
        # Last move from and to squares
        for sq in [last_move.from_square, last_move.to_square]:
            rect = _get_square_rect(sq, bx, by)
            hl = Image.new('RGBA', (sq_sz, sq_sz), (246, 246, 105, 180)) # #F6F669 alpha=180
            img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
            
    if board.is_check():
        king_sq = board.king(board.turn)
        if king_sq is not None:
            rect = _get_square_rect(king_sq, bx, by)
            hl = Image.new('RGBA', (sq_sz, sq_sz), (255, 0, 0, 120))
            img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
            
    # Load piece images
    global PIECE_IMAGE_CACHE
    unicode_font = get_unicode_font()
    pieces_dir = os.path.join("assets", "pieces", "cburnett")
    
    def draw_piece(symbol, cx, cy):
        pname = PIECE_MAP[symbol]
        path = os.path.join(pieces_dir, f"{pname}.png")
        if os.path.exists(path):
            if pname not in PIECE_IMAGE_CACHE:
                p_img = Image.open(path).convert("RGBA")
                p_img = p_img.resize((110, 110), Image.Resampling.LANCZOS)
                PIECE_IMAGE_CACHE[pname] = p_img
            p_img = PIECE_IMAGE_CACHE[pname]
            img.alpha_composite(p_img, (int(cx - 55), int(cy - 55)))
        else:
            u_sym = PIECE_SYMBOLS[symbol]
            draw.text((cx, cy), u_sym, font=unicode_font, fill="black", anchor="mm")

    # Draw static pieces
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece:
            if moving_piece and sq == moving_piece['from_sq']:
                continue
            cx, cy = _get_square_center(sq, bx, by)
            draw_piece(piece.symbol(), cx, cy)
            
    # Draw moving piece
    if moving_piece and moving_pos:
        draw_piece(moving_piece['symbol'], moving_pos[0], moving_pos[1])
        
    return img.convert('RGB')

def generate_frames(fen: str, moves: List[str], player: str = "Player", opponent: str = "Opponent", event: str = "Event", year: str = "2023", section_times: list = None, cta_text: str = None, output_dir: str = "outputs") -> dict:
    logger.info("Generating board frames using PIL animation (30s timeline)...")
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    # clear existing frames
    for f in os.listdir(frames_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(frames_dir, f))
            
    board = chess.Board(fen) if fen else chess.Board()
    frame_idx = 0
    frame_paths = []
    fonts = load_all_fonts()
    
    import glob
    bg_files = sorted(glob.glob("assets/backgrounds/*.png"))
    bgs = [Image.open(f).convert('RGBA') for f in bg_files] if bg_files else []
    
    anim_frames = 6     # 200ms
    pre_hold = 12       # 400ms
    post_hold = 18      # 600ms
    intro_frames = 60   # 2.0s
    outro_frames = 60   # 2.0s
    
    # Pre-calculate min_frames
    expected_moves_frames = intro_frames
    if len(moves) > 0:
        expected_moves_frames += len(moves) * (anim_frames + post_hold)
        expected_moves_frames += (len(moves) - 1) * pre_hold
        
    temp_board = chess.Board(fen) if fen else chess.Board()
    for m in moves: temp_board.push(chess.Move.from_uci(m))
    if temp_board.is_checkmate():
        expected_moves_frames += 30
        
    min_frames = expected_moves_frames + outro_frames
    if section_times:
        voice_frames = int((section_times[-1]['end'] + 0.5) * 30)
        min_frames = max(min_frames, voice_frames)
        
    extra_data = {
        "player": player,
        "opponent": opponent,
        "event": event,
        "year": year,
        "section_times": section_times or [],
        "cta_text": cta_text or "Comment your move before I show mine!",
        "duration": min_frames / 30.0,
        "sol_moves": moves,
        "fonts": fonts,
        "bgs": bgs
    }
    
    def save_frame(img: Image.Image):
        nonlocal frame_idx
        path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.png")
        t = frame_idx / 30.0
        vertical_img = pad_to_vertical(img, "story", t, extra_data)
        vertical_img.save(path)
        frame_paths.append(path)
        frame_idx += 1
        
    bx = (1080 - 1040) // 2 + 40
    by = (1080 - 1040) // 2 + 40
    last_move = None
    move_timestamps = []
    
    def ease_in_out(t):
        return t * t * (3.0 - 2.0 * t)

    # Intro hold
    if len(moves) > 0:
        base_img = _render_state(board, fonts=fonts)
        for _ in range(intro_frames):
            save_frame(base_img)
            
        for i in range(len(moves)):
            move_uci = moves[i]
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                board.push(move)
                continue
                
            piece = board.piece_at(move.from_square)
            if not piece:
                board.push(move)
                continue
                
            moving_piece = {'symbol': piece.symbol(), 'from_sq': move.from_square}
            is_capture = board.is_capture(move)
            start_x, start_y = _get_square_center(move.from_square, bx, by)
            end_x, end_y = _get_square_center(move.to_square, bx, by)
            
            # Pre-hold (skip for move 0 since intro covers it)
            if i > 0:
                hold_img = _render_state(board, last_move=last_move, fonts=fonts)
                for _ in range(pre_hold):
                    save_frame(hold_img)
                    
            # Animate
            for f in range(anim_frames):
                progress = f / float(max(1, anim_frames - 1))
                progress = ease_in_out(progress)
                cur_x = start_x + (end_x - start_x) * progress
                cur_y = start_y + (end_y - start_y) * progress
                img = _render_state(board, moving_piece, (cur_x, cur_y), last_move, fonts)
                save_frame(img)
                
            move_timestamps.append({
                "move": i,
                "frame": frame_idx,
                "time": frame_idx / 30.0,
                "is_capture": is_capture
            })
            
            board.push(move)
            last_move = move
            
            # Post-hold
            hold_img = _render_state(board, last_move=last_move, fonts=fonts)
            for _ in range(post_hold):
                save_frame(hold_img)
    else:
        base_img = _render_state(board, fonts=fonts)
        for _ in range(intro_frames + outro_frames):
            save_frame(base_img)
            
    # Pad to cover voiceover if needed, plus outro
    # min_frames already calculated
    
    # Checkmate explicit highlight
    if board.is_checkmate():
        logger.info("Checkmate detected! Adding explicit checkmate highlight sequence.")
        king_sq = board.king(board.turn)
        rect = _get_square_rect(king_sq, bx, by)
        for _ in range(3): # Flash 3 times
            # Red flash
            hl_img = _render_state(board, last_move=last_move, fonts=fonts).convert("RGBA")
            hl = Image.new('RGBA', (120, 120), (255, 0, 0, 180))
            hl_img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
            hl_img = hl_img.convert("RGB")
            for _ in range(5):
                save_frame(hl_img)
            
            # Normal frame
            norm_img = _render_state(board, last_move=last_move, fonts=fonts)
            for _ in range(5):
                save_frame(norm_img)
                
    final_img = _render_state(board, last_move=last_move, fonts=fonts)
    while frame_idx < min_frames:
        save_frame(final_img)
        
    extra_data["duration"] = frame_idx / 30.0
        
    logger.info(f"Generated {len(frame_paths)} frames.")
    return {
        "frames": frame_paths,
        "move_timestamps": move_timestamps,
        "total_frames": len(frame_paths),
        "duration": len(frame_paths) / 30.0
    }

def generate_flash_frames(fen: str, moves: List[str], rating: int = 1500, themes: List[str] = None, cta_text: str = None, output_dir: str = "outputs") -> dict:
    logger.info("Generating board frames using PIL animation (10s Flash timeline)...")
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    # clear existing frames
    for f in os.listdir(frames_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(frames_dir, f))
            
    board = chess.Board(fen) if fen else chess.Board()
    frame_idx = 0
    frame_paths = []
    fonts = load_all_fonts()
    
    import glob
    bg_files = sorted(glob.glob("assets/backgrounds/*.png"))
    bgs = [Image.open(f).convert('RGBA') for f in bg_files] if bg_files else []
    
    anim_frames = 6
    pre_hold = 12
    post_hold = 18
    intro_frames = 60
    outro_frames = 60
    stakes_text = "Find the winning move!"
    
    # Calculate expected duration
    total_frames = intro_frames + outro_frames
    if len(moves) > 0:
        total_frames += len(moves) * (anim_frames + post_hold)
        total_frames += (len(moves) - 1) * (pre_hold + 15) # 15 is 3 * 5 flashes
        
    temp_board = chess.Board(fen) if fen else chess.Board()
    for m in moves: temp_board.push(chess.Move.from_uci(m))
    if temp_board.is_checkmate():
        total_frames += 30
        
    extra_data = {
        "rating": rating,
        "stakes_text": stakes_text,
        "sol_moves": moves,
        "cta_text": cta_text or "Comment your move before I show mine!",
        "duration": total_frames / 30.0,
        "fonts": fonts,
        "bgs": bgs
    }
    
    def save_frame(img: Image.Image):
        nonlocal frame_idx
        path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.png")
        t = frame_idx / 30.0
        vertical_img = pad_to_vertical(img, "flash", t, extra_data)
        vertical_img.save(path)
        frame_paths.append(path)
        frame_idx += 1
        
    bx = (1080 - 1040) // 2 + 40
    by = (1080 - 1040) // 2 + 40
    last_move = None
    move_timestamps = []
    
    anim_frames = 6
    pre_hold = 12
    post_hold = 18
    intro_frames = 60
    outro_frames = 60
    
    def ease_in_out(t):
        return t * t * (3.0 - 2.0 * t)
        
    if len(moves) > 0:
        base_img = _render_state(board, fonts=fonts)
        for _ in range(intro_frames):
            save_frame(base_img)
            
        for i in range(len(moves)):
            move_uci = moves[i]
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                board.push(move)
                continue
                
            piece = board.piece_at(move.from_square)
            if not piece:
                board.push(move)
                continue
                
            moving_piece = {'symbol': piece.symbol(), 'from_sq': move.from_square}
            is_capture = board.is_capture(move)
            start_x, start_y = _get_square_center(move.from_square, bx, by)
            end_x, end_y = _get_square_center(move.to_square, bx, by)
            
            if i > 0:
                hold_img = _render_state(board, last_move=last_move, fonts=fonts)
                for _ in range(pre_hold):
                    save_frame(hold_img)
                    
            for f in range(anim_frames):
                progress = f / float(max(1, anim_frames - 1))
                progress = ease_in_out(progress)
                cur_x = start_x + (end_x - start_x) * progress
                cur_y = start_y + (end_y - start_y) * progress
                img = _render_state(board, moving_piece, (cur_x, cur_y), last_move, fonts)
                save_frame(img)
                
            move_timestamps.append({
                "move": i,
                "frame": frame_idx,
                "time": frame_idx / 30.0,
                "is_capture": is_capture
            })
            
            board.push(move)
            last_move = move
            
            hold_img = _render_state(board, last_move=last_move, fonts=fonts)
            for _ in range(post_hold):
                save_frame(hold_img)
                
            # Flashes for correct solution
            if i > 0:
                for flash_i in range(3):
                    color = (0, 255, 0, 150) if flash_i % 2 == 0 else (255, 255, 0, 150)
                    flash_img = _render_state(board, last_move=last_move, fonts=fonts).convert("RGBA")
                    rect = _get_square_rect(move.to_square, bx, by)
                    hl = Image.new('RGBA', (120, 120), color)
                    flash_img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
                    flash_img = flash_img.convert("RGB")
                    for _ in range(5):
                        save_frame(flash_img)
    else:
        base_img = _render_state(board, fonts=fonts)
        for _ in range(intro_frames):
            save_frame(base_img)
            
    # Checkmate explicit highlight
    if board.is_checkmate():
        logger.info("Checkmate detected! Adding explicit checkmate highlight sequence.")
        king_sq = board.king(board.turn)
        rect = _get_square_rect(king_sq, bx, by)
        for _ in range(3): # Flash 3 times
            # Red flash
            hl_img = _render_state(board, last_move=last_move, fonts=fonts).convert("RGBA")
            hl = Image.new('RGBA', (120, 120), (255, 0, 0, 180))
            hl_img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
            hl_img = hl_img.convert("RGB")
            for _ in range(5):
                save_frame(hl_img)
            
            # Normal frame
            norm_img = _render_state(board, last_move=last_move, fonts=fonts)
            for _ in range(5):
                save_frame(norm_img)

    final_img = _render_state(board, last_move=last_move, fonts=fonts)
    for _ in range(outro_frames):
        save_frame(final_img)
        
    extra_data["duration"] = frame_idx / 30.0
        
    logger.info(f"Generated {len(frame_paths)} frames for Flash.")
    return {
        "frames": frame_paths,
        "move_timestamps": move_timestamps,
        "total_frames": len(frame_paths),
        "duration": len(frame_paths) / 30.0
    }

def generate_series_frames(fen: str, moves: List[str], number: int, rating: int = 1500, themes: List[str] = None, cta_text: str = None, output_dir: str = "outputs") -> dict:
    logger.info(f"Generating Series frames for #{number} (15s timeline)...")
    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    for f in os.listdir(frames_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(frames_dir, f))
            
    board = chess.Board(fen) if fen else chess.Board()
    frame_idx = 0
    frame_paths = []
    fonts = load_all_fonts()
    
    difficulty = "Intermediate"
    if rating < 1400: difficulty = "Beginner"
    elif rating < 1600: difficulty = "Intermediate"
    elif rating < 1800: difficulty = "Advanced"
    elif rating < 2000: difficulty = "Expert"
    else: difficulty = "Grandmaster Level"
    
    theme = themes[0].capitalize() if themes else "Tactics"
    
    import glob
    bg_files = sorted(glob.glob("assets/backgrounds/*.png"))
    bgs = [Image.open(f).convert('RGBA') for f in bg_files] if bg_files else []
    
    anim_frames = 6
    pre_hold = 12
    post_hold = 18
    intro_frames = 60
    outro_frames = 60
    
    # Calculate expected duration
    total_frames = intro_frames + outro_frames
    if len(moves) > 0:
        total_frames += len(moves) * (anim_frames + post_hold)
        total_frames += (len(moves) - 1) * (pre_hold + 15) # 15 is 3 * 5 flashes
        
    temp_board = chess.Board(fen) if fen else chess.Board()
    for m in moves: temp_board.push(chess.Move.from_uci(m))
    if temp_board.is_checkmate():
        total_frames += 30
        
    extra_data = {
        "number": number,
        "rating": rating,
        "themes": themes,
        "theme": theme,
        "difficulty": difficulty,
        "sol_moves": moves,
        "cta_text": cta_text or "Comment your move before I show mine!",
        "duration": total_frames / 30.0,
        "fonts": fonts,
        "bgs": bgs
    }
    
    def save_frame(img: Image.Image):
        nonlocal frame_idx
        path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.png")
        t = frame_idx / 30.0
        vertical_img = pad_to_vertical(img, "series", t, extra_data)
        vertical_img.save(path)
        frame_paths.append(path)
        frame_idx += 1
        
    bx = (1080 - 1040) // 2 + 40
    by = (1080 - 1040) // 2 + 40
    last_move = None
    move_timestamps = []
    
    # Load watermark font once
    watermark_font = fonts[28]
    
    def add_watermark(img: Image.Image) -> Image.Image:
        draw = ImageDraw.Draw(img)
        text = f"#{number}"
        draw.text((bx + 960 - 10, by + 960 + 10), text, font=watermark_font, fill="#555555", anchor="rd")
        return img
        

    
    def ease_in_out(t):
        return t * t * (3.0 - 2.0 * t)
        
    if len(moves) > 0:
        base_img = add_watermark(_render_state(board, fonts=fonts))
        for _ in range(intro_frames):
            save_frame(base_img)
            
        for i in range(len(moves)):
            move_uci = moves[i]
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                board.push(move)
                continue
                
            piece = board.piece_at(move.from_square)
            if not piece:
                board.push(move)
                continue
                
            moving_piece = {'symbol': piece.symbol(), 'from_sq': move.from_square}
            is_capture = board.is_capture(move)
            start_x, start_y = _get_square_center(move.from_square, bx, by)
            end_x, end_y = _get_square_center(move.to_square, bx, by)
            
            if i > 0:
                hold_img = add_watermark(_render_state(board, last_move=last_move, fonts=fonts))
                for _ in range(pre_hold):
                    save_frame(hold_img)
                    
            for f in range(anim_frames):
                progress = f / float(max(1, anim_frames - 1))
                progress = ease_in_out(progress)
                cur_x = start_x + (end_x - start_x) * progress
                cur_y = start_y + (end_y - start_y) * progress
                img = _render_state(board, moving_piece, (cur_x, cur_y), last_move, fonts)
                save_frame(add_watermark(img))
                
            move_timestamps.append({
                "move": i,
                "frame": frame_idx,
                "time": frame_idx / 30.0,
                "is_capture": is_capture
            })
            
            board.push(move)
            last_move = move
            
            hold_img = add_watermark(_render_state(board, last_move=last_move, fonts=fonts))
            for _ in range(post_hold):
                save_frame(hold_img)
                
            # Flashes for correct solution
            if i > 0:
                for flash_i in range(3):
                    color = (0, 255, 0, 150) if flash_i % 2 == 0 else (255, 255, 0, 150)
                    flash_img = _render_state(board, last_move=last_move, fonts=fonts).convert("RGBA")
                    rect = _get_square_rect(move.to_square, bx, by)
                    hl = Image.new('RGBA', (120, 120), color)
                    flash_img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
                    flash_img = flash_img.convert("RGB")
                    for _ in range(5):
                        save_frame(add_watermark(flash_img))
    else:
        base_img = add_watermark(_render_state(board, fonts=fonts))
        for _ in range(intro_frames):
            save_frame(base_img)
            
    # Checkmate explicit highlight
    if board.is_checkmate():
        logger.info("Checkmate detected! Adding explicit checkmate highlight sequence.")
        king_sq = board.king(board.turn)
        rect = _get_square_rect(king_sq, bx, by)
        for _ in range(3): # Flash 3 times
            # Red flash
            hl_img = add_watermark(_render_state(board, last_move=last_move, fonts=fonts).convert("RGBA"))
            hl = Image.new('RGBA', (120, 120), (255, 0, 0, 180))
            hl_img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
            hl_img = hl_img.convert("RGB")
            for _ in range(5):
                save_frame(hl_img)
            
            # Normal frame
            norm_img = add_watermark(_render_state(board, last_move=last_move, fonts=fonts))
            for _ in range(5):
                save_frame(norm_img)

    final_img = add_watermark(_render_state(board, last_move=last_move, fonts=fonts))
    for _ in range(outro_frames):
        save_frame(final_img)
        
    extra_data["duration"] = frame_idx / 30.0
        
    logger.info(f"Generated {len(frame_paths)} frames for Series.")
    return {
        "frames": frame_paths,
        "move_timestamps": move_timestamps,
        "total_frames": len(frame_paths),
        "duration": len(frame_paths) / 30.0
    }
