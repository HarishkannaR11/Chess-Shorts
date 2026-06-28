import logging
import aiosqlite
import json
import os

logger = logging.getLogger(__name__)

DB_PATH = "database/chess_shorts.db"

async def init_db():
    logger.info("Initializing database...")
    os.makedirs("database", exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                youtube_url TEXT,
                video_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                thumbnail_path TEXT,
                video_path TEXT,
                script_json TEXT,
                format TEXT DEFAULT 'story',
                hook TEXT
            )
        ''')
        
        # Safe migration if table exists without these columns
        cursor = await db.execute("PRAGMA table_info(videos)")
        columns = [row[1] for row in await cursor.fetchall()]
        if 'format' not in columns:
            await db.execute("ALTER TABLE videos ADD COLUMN format TEXT DEFAULT 'story'")
        if 'hook' not in columns:
            await db.execute("ALTER TABLE videos ADD COLUMN hook TEXT")
            
        await db.execute('''
            CREATE TABLE IF NOT EXISTS used_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fen TEXT,
                player TEXT,
                event TEXT,
                hook_text TEXT,
                format TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS puzzles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fen TEXT,
                moves TEXT,
                rating INTEGER,
                theme TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS puzzle_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                puzzle_number INTEGER UNIQUE,
                fen TEXT,
                moves TEXT,
                rating INTEGER,
                theme TEXT,
                video_path TEXT,
                thumbnail_path TEXT,
                youtube_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS local_puzzles (
                id TEXT PRIMARY KEY,
                fen TEXT,
                moves TEXT,
                rating INTEGER,
                themes TEXT
            )
        ''')
        await db.commit()
        logger.info("Database initialized successfully.")

async def save_video(data: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            INSERT INTO videos (title, description, status, thumbnail_path, video_path, script_json, format, hook)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get("title"),
            data.get("description"),
            data.get("status", "pending"),
            data.get("thumbnail_path"),
            data.get("video_path"),
            json.dumps(data.get("script_json", {})),
            data.get("format", "story"),
            data.get("hook")
        ))
        await db.commit()
        return cursor.lastrowid

async def get_all_videos() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM videos ORDER BY created_at DESC')
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

async def update_video_status(video_id: int, status: str, youtube_url: str = None, yt_video_id: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            UPDATE videos 
            SET status = ?, youtube_url = ?, video_id = ?
            WHERE id = ?
        ''', (status, youtube_url, yt_video_id, video_id))
        await db.commit()

async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT COUNT(*) FROM videos')
        total = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM videos WHERE status = 'uploaded'")
        uploaded = (await cursor.fetchone())[0]
        
        cursor = await db.execute("SELECT COUNT(*) FROM videos WHERE status = 'pending'")
        pending = (await cursor.fetchone())[0]
        
        return {
            "total_videos": total,
            "uploaded": uploaded,
            "pending": pending
        }

async def delete_video(video_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
        row = await cursor.fetchone()
        if row:
            await db.execute('DELETE FROM videos WHERE id = ?', (video_id,))
            await db.commit()
            return dict(row)
        return None

async def is_fen_used(fen: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT 1 FROM used_content WHERE fen = ?', (fen,))
        return await cursor.fetchone() is not None

async def is_hook_used_recently(hook: str, last_n: int = 10) -> bool:
    if not hook:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT hook_text FROM used_content ORDER BY created_at DESC LIMIT ?', (last_n,))
        rows = await cursor.fetchall()
        for row in rows:
            if row[0] == hook:
                return True
        return False

async def get_last_champion() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT player FROM used_content WHERE format = 'story' AND player IS NOT NULL ORDER BY created_at DESC LIMIT 1")
        row = await cursor.fetchone()
        if row:
            return row[0]
        return ""

async def mark_content_used(fen: str, player: str = None, event: str = None, hook: str = None, format: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO used_content (fen, player, event, hook_text, format)
            VALUES (?, ?, ?, ?, ?)
        ''', (fen, player, event, hook, format))
        await db.commit()

# --- Puzzle Series Functions ---

async def get_next_puzzle_number() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(puzzle_number) FROM puzzle_series") as cursor:
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return row[0] + 1
            return 1

async def is_puzzle_number_used(number: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM puzzle_series WHERE puzzle_number = ?", (number,)) as cursor:
            return await cursor.fetchone() is not None

async def save_series_puzzle(data: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('''
            INSERT INTO puzzle_series (
                puzzle_number, fen, moves, rating, theme, 
                video_path, thumbnail_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        ''', (
            data.get('puzzle_number'),
            data.get('fen'),
            data.get('moves'),
            data.get('rating'),
            data.get('theme'),
            data.get('video_path'),
            data.get('thumbnail_path')
        ))
        await db.commit()
        return cursor.lastrowid

async def get_all_series() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM puzzle_series ORDER BY puzzle_number ASC") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_series_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), SUM(CASE WHEN status='uploaded' THEN 1 ELSE 0 END), MAX(puzzle_number) FROM puzzle_series") as cursor:
            row = await cursor.fetchone()
            total = row[0] or 0
            uploaded = row[1] or 0
            last_num = row[2] or 0
            
        async with db.execute("SELECT rating FROM puzzle_series") as cursor:
            ratings = [r[0] for r in await cursor.fetchall()]
            
        breakdown = {
            "beginner": len([r for r in ratings if r < 1400]),
            "intermediate": len([r for r in ratings if 1400 <= r < 1600]),
            "advanced": len([r for r in ratings if 1600 <= r < 1800]),
            "expert": len([r for r in ratings if 1800 <= r < 2000]),
            "grandmaster": len([r for r in ratings if r >= 2000])
        }
        
        return {
            "total_generated": total,
            "total_uploaded": uploaded,
            "next_number": last_num + 1,
            "difficulty_breakdown": breakdown
        }

async def get_local_puzzle(min_rating: int, max_rating: int) -> dict | None:
    """Fetch a random local puzzle in the specified rating range that hasn't been used yet."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        cursor = await db.execute(f'''
            SELECT id, fen, moves, rating, themes 
            FROM local_puzzles 
            WHERE rating >= ? AND rating <= ?
            AND fen NOT IN (SELECT fen FROM used_content)
            ORDER BY RANDOM() LIMIT 1
        ''', (min_rating, max_rating))
        
        row = await cursor.fetchone()
        if not row:
            return None
            
        return {
            "game": {"pgn": row["fen"]},
            "puzzle": {
                "id": row["id"],
                "rating": row["rating"],
                "solution": row["moves"].split(),
                "themes": row["themes"].split() if row["themes"] else ["Tactics"]
            }
        }
