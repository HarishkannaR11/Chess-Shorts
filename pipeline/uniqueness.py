import sqlite3
import os

DB_PATH = os.path.join("database", "uniqueness.db")

def init_uniqueness_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS used_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fen TEXT UNIQUE,
                player TEXT,
                tactic TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def is_unique(fen: str) -> bool:
    init_uniqueness_db()
    # 1. Check permanent duplicate in uniqueness.db
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM used_history WHERE fen = ?", (fen,))
        if cursor.fetchone() is not None:
            return False
            
    # 2. Check 14-day duplicate/near-duplicate in both databases
    import chess
    cand_board = chess.Board(fen)
    cand_placement = fen.split()[0]
    
    recent_fens = []
    # Fetch from uniqueness.db (last 14 days)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT fen FROM used_history WHERE timestamp >= datetime('now', '-14 days')")
        recent_fens.extend([r[0] for r in cursor.fetchall() if r[0]])
        
    # Fetch from chess_shorts.db (last 14 days)
    try:
        with sqlite3.connect("database/chess_shorts.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT fen FROM used_content WHERE created_at >= datetime('now', '-14 days')")
            recent_fens.extend([r[0] for r in cursor.fetchall() if r[0]])
    except Exception:
        pass
        
    for ref_fen in set(recent_fens):
        if ref_fen.split()[0] == cand_placement:
            return False
        try:
            ref_board = chess.Board(ref_fen)
            diff_squares = 0
            for sq in chess.SQUARES:
                if cand_board.piece_at(sq) != ref_board.piece_at(sq):
                    diff_squares += 1
                    if diff_squares > 8:
                        break
            if diff_squares <= 8:
                return False
        except Exception:
            continue
            
    return True

def mark_used(fen: str, player: str, tactic: str):
    init_uniqueness_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO used_history (fen, player, tactic) VALUES (?, ?, ?)",
                (fen, player, tactic)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass

def get_variety_constraints() -> dict:
    init_uniqueness_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT player, tactic FROM used_history ORDER BY id DESC LIMIT 100")
        history = cursor.fetchall()
        
        avoid_player = None
        if history and history[0][0]:
            avoid_player = history[0][0]
            
        avoid_tactic = None
        if len(history) >= 3:
            tactics = [row[1] for row in history[:3] if row[1]]
            if len(tactics) == 3 and len(set(tactics)) == 1:
                avoid_tactic = tactics[0]
                
        return {
            "avoid_player": avoid_player,
            "avoid_tactic": avoid_tactic
        }
