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
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM used_history WHERE fen = ?", (fen,))
        return cursor.fetchone() is None

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
