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

def get_unicode_font():
    try:
        if os.name == 'nt':
            font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\seguisym.ttf'
            if not os.path.exists(font_path):
                font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\arial.ttf'
            return ImageFont.truetype(font_path, 80)
        else:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 80)
    except Exception:
        return ImageFont.load_default()

def get_text_font(size=20):
    try:
        if os.name == 'nt':
            font_path = os.environ.get('WINDIR', 'C:\\Windows') + '\\Fonts\\arialbd.ttf'
            return ImageFont.truetype(font_path, size)
        else:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()

def _get_material_eval(board: chess.Board):
    values = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
    w = sum(values[p.piece_type] for p in board.piece_map().values() if p.color == chess.WHITE)
    b = sum(values[p.piece_type] for p in board.piece_map().values() if p.color == chess.BLACK)
    return w - b

def _draw_eval_bar(draw: ImageDraw, board: chess.Board, x_offset: int, y_offset: int, h: int):
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
    txt_font = get_text_font(18)
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

def _render_state(board: chess.Board, moving_piece=None, moving_pos=None, last_move=None) -> Image.Image:
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
    font = get_text_font(20)
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
    _draw_eval_bar(draw, board, bx - border - 30, by, board_sz)
    
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
    piece_cache = {}
    unicode_font = get_unicode_font()
    pieces_dir = os.path.join("assets", "pieces", "cburnett")
    
    def draw_piece(symbol, cx, cy):
        pname = PIECE_MAP[symbol]
        path = os.path.join(pieces_dir, f"{pname}.png")
        if os.path.exists(path):
            if pname not in piece_cache:
                p_img = Image.open(path).convert("RGBA")
                p_img = p_img.resize((110, 110), Image.Resampling.LANCZOS)
                piece_cache[pname] = p_img
            p_img = piece_cache[pname]
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

def generate_frames(fen: str, moves: List[str]) -> dict:
    logger.info("Generating board frames using PIL animation (30s timeline)...")
    frames_dir = os.path.join("outputs", "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    # clear existing frames
    for f in os.listdir(frames_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(frames_dir, f))
            
    board = chess.Board(fen) if fen else chess.Board()
    frame_idx = 0
    frame_paths = []
    
    def save_frame(img: Image.Image):
        nonlocal frame_idx
        path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.png")
        img.save(path)
        frame_paths.append(path)
        frame_idx += 1
        
    bx = (1080 - 1040) // 2 + 40
    by = (1080 - 1040) // 2 + 40
    last_move = None
    move_timestamps = []
    
    base_img = _render_state(board)
    
    # Phase 1: 0-8s (240 frames) - Initial static board
    for _ in range(240):
        save_frame(base_img)
        
    # Phase 2: 8-22s (420 frames) - Moves
    num_moves = len(moves)
    if num_moves == 0:
        for _ in range(420):
            save_frame(base_img)
    else:
        anim_frames = int(os.environ.get("ANIMATION_FRAMES_PER_MOVE", 8))
        frames_per_move = max(anim_frames + 1, 420 // num_moves)
        hold_frames = frames_per_move - anim_frames
        for i, move_uci in enumerate(moves):
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                logger.warning(f"Move {move_uci} is illegal, pushing anyway.")
                
            piece = board.piece_at(move.from_square)
            if not piece:
                board.push(move)
                for _ in range(frames_per_move):
                    save_frame(_render_state(board, last_move=last_move))
                continue
                
            moving_piece = {
                'symbol': piece.symbol(),
                'from_sq': move.from_square
            }
            
            is_capture = board.is_capture(move)
            
            start_x, start_y = _get_square_center(move.from_square, bx, by)
            end_x, end_y = _get_square_center(move.to_square, bx, by)
            
            # Animation frames
            for f in range(anim_frames):
                progress = f / float(max(1, anim_frames - 1))
                cur_x = start_x + (end_x - start_x) * progress
                cur_y = start_y + (end_y - start_y) * progress
                
                img = _render_state(board, moving_piece, (cur_x, cur_y), last_move)
                save_frame(img)
                
            move_timestamps.append({
                "move": i,
                "frame": frame_idx,
                "time": frame_idx / 30.0,
                "is_capture": is_capture
            })
            
            board.push(move)
            last_move = move
            
            # Hold frames
            hold_img = _render_state(board, last_move=last_move)
            for _ in range(hold_frames):
                save_frame(hold_img)
                
        # Pad any remainder frames due to integer division
        while frame_idx < (240 + 420):
            save_frame(hold_img)
            
    # Phase 3: 22-30s (240 frames) - Final static board
    final_img = _render_state(board, last_move=last_move)
    while frame_idx < 900:
        save_frame(final_img)
            
    logger.info(f"Generated {len(frame_paths)} frames.")
    return {
        "frames": frame_paths,
        "move_timestamps": move_timestamps,
        "total_frames": len(frame_paths),
        "duration": len(frame_paths) / 30.0
    }

def generate_flash_frames(fen: str, moves: List[str]) -> dict:
    logger.info("Generating board frames using PIL animation (10s Flash timeline)...")
    frames_dir = os.path.join("outputs", "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    # clear existing frames
    for f in os.listdir(frames_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(frames_dir, f))
            
    board = chess.Board(fen) if fen else chess.Board()
    frame_idx = 0
    frame_paths = []
    
    def save_frame(img: Image.Image):
        nonlocal frame_idx
        path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.png")
        img.save(path)
        frame_paths.append(path)
        frame_idx += 1
        
    bx = (1080 - 1040) // 2 + 40
    by = (1080 - 1040) // 2 + 40
    last_move = None
    move_timestamps = []
    
    base_img = _render_state(board)
    
    # Initial hold: 60 frames (2 seconds)
    for _ in range(60):
        save_frame(base_img)
        
    anim_frames = 8
    hold_frames = 12
    
    for i, move_uci in enumerate(moves):
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            board.push(move)
            continue
            
        piece = board.piece_at(move.from_square)
        if not piece:
            board.push(move)
            continue
            
        moving_piece = {
            'symbol': piece.symbol(),
            'from_sq': move.from_square
        }
        
        is_capture = board.is_capture(move)
        
        start_x, start_y = _get_square_center(move.from_square, bx, by)
        end_x, end_y = _get_square_center(move.to_square, bx, by)
        
        # 8 Animation frames
        for f in range(anim_frames):
            progress = f / float(max(1, anim_frames - 1))
            cur_x = start_x + (end_x - start_x) * progress
            cur_y = start_y + (end_y - start_y) * progress
            
            img = _render_state(board, moving_piece, (cur_x, cur_y), last_move)
            save_frame(img)
            
        move_timestamps.append({
            "move": i,
            "frame": frame_idx,
            "time": frame_idx / 30.0,
            "is_capture": is_capture
        })
        
        board.push(move)
        last_move = move
        
        # 12 Hold frames + 3 flashes (5 frames each = 15 frames total)
        # Wait, user said: "After each move: flash highlight on destination square (alternate between yellow and green, 3 flashes, 5 frames each)"
        # So 15 frames of flashing instead of 12 hold? Or 12 hold THEN flash?
        # Let's just do 15 frames of flash holding.
        
        for flash_i in range(3):
            # flash_i=0 (green), flash_i=1 (yellow), flash_i=2 (green)
            color = (0, 255, 0, 150) if flash_i % 2 == 0 else (255, 255, 0, 150)
            
            # draw base state
            flash_img = _render_state(board, last_move=last_move).convert("RGBA")
            # add flash box
            rect = _get_square_rect(move.to_square, bx, by)
            hl = Image.new('RGBA', (120, 120), color)
            flash_img.alpha_composite(hl, (int(rect[0]), int(rect[1])))
            flash_img = flash_img.convert("RGB")
            
            for _ in range(5):
                save_frame(flash_img)
                
    # Final hold: 30 frames
    final_img = _render_state(board, last_move=last_move)
    for _ in range(30):
        save_frame(final_img)
        
    logger.info(f"Generated {len(frame_paths)} frames for Flash.")
    return {
        "frames": frame_paths,
        "move_timestamps": move_timestamps,
        "total_frames": len(frame_paths),
        "duration": len(frame_paths) / 30.0
    }

def generate_series_frames(fen: str, moves: list, number: int) -> dict:
    logger.info(f"Generating Series frames for #{number} (15s timeline)...")
    frames_dir = os.path.join("outputs", "frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    for f in os.listdir(frames_dir):
        if f.endswith('.png'):
            os.remove(os.path.join(frames_dir, f))
            
    board = chess.Board(fen) if fen else chess.Board()
    frame_idx = 0
    frame_paths = []
    
    def save_frame(img: Image.Image):
        nonlocal frame_idx
        path = os.path.join(frames_dir, f"frame_{frame_idx:04d}.png")
        img.save(path)
        frame_paths.append(path)
        frame_idx += 1
        
    bx = (1080 - 1040) // 2 + 40
    by = (1080 - 1040) // 2 + 40
    last_move = None
    move_timestamps = []
    
    def add_watermark(img: Image.Image) -> Image.Image:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arialbd.ttf", 28)
        except:
            font = ImageFont.load_default()
        text = f"#{number}"
        # Bottom right of the border
        # border ends at by + 960 + 40 = by + 1000
        # bx + 1000
        draw.text((bx + 960 - 10, by + 960 + 10), text, font=font, fill="#555555", anchor="rd")
        return img
    
    base_img = add_watermark(_render_state(board))
    
    # Initial hold: 90 frames (3 seconds)
    for _ in range(90):
        save_frame(base_img)
        
    anim_frames = 8
    hold_frames = 15
    
    for i, move_uci in enumerate(moves):
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            board.push(move)
            continue
            
        piece = board.piece_at(move.from_square)
        if not piece:
            board.push(move)
            continue
            
        moving_piece = {
            'symbol': piece.symbol(),
            'from_sq': move.from_square
        }
        
        is_capture = board.is_capture(move)
        start_x, start_y = _get_square_center(move.from_square, bx, by)
        end_x, end_y = _get_square_center(move.to_square, bx, by)
        
        for f in range(anim_frames):
            progress = f / float(max(1, anim_frames - 1))
            cur_x = start_x + (end_x - start_x) * progress
            cur_y = start_y + (end_y - start_y) * progress
            
            img = _render_state(board, moving_piece, (cur_x, cur_y), last_move)
            save_frame(add_watermark(img))
            
        move_timestamps.append({
            "move": i,
            "frame": frame_idx,
            "time": frame_idx / 30.0,
            "is_capture": is_capture
        })
        
        board.push(move)
        last_move = move
        
        hold_img = add_watermark(_render_state(board, last_move=last_move))
        for _ in range(hold_frames):
            save_frame(hold_img)
            
    final_img = add_watermark(_render_state(board, last_move=last_move))
    # Pad to 450 frames (15s)
    while frame_idx < 450:
        save_frame(final_img)
        
    logger.info(f"Generated {len(frame_paths)} frames for Series.")
    return {
        "frames": frame_paths,
        "move_timestamps": move_timestamps,
        "total_frames": len(frame_paths),
        "duration": len(frame_paths) / 30.0
    }
