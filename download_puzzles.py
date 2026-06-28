import requests
import zstandard as zstd
import io
import csv
import sqlite3

def download_puzzles(limit=50000):
    url = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
    print(f"Downloading first {limit} puzzles from Lichess...")
    
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        
        dctx = zstd.ZstdDecompressor()
        
        conn = sqlite3.connect('chess_shorts.db')
        c = conn.cursor()
        
        with dctx.stream_reader(r.raw) as reader:
            text_stream = io.TextIOWrapper(reader, encoding='utf-8')
            csv_reader = csv.reader(text_stream)
            
            # Skip header
            next(csv_reader)
            
            count = 0
            batch = []
            for row in csv_reader:
                if len(row) < 8:
                    continue
                
                # PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl,OpeningTags
                pid, fen, moves, rating, _, _, _, themes, _, _ = row[:10] if len(row) >= 10 else row + ["", ""]
                
                try:
                    rating = int(rating)
                except:
                    rating = 1500
                    
                batch.append((pid, fen, moves, rating, themes))
                count += 1
                
                if count % 1000 == 0:
                    c.executemany("INSERT OR IGNORE INTO local_puzzles (id, fen, moves, rating, themes) VALUES (?, ?, ?, ?, ?)", batch)
                    conn.commit()
                    batch = []
                    print(f"Loaded {count} puzzles...")
                
                if count >= limit:
                    break
            
            if batch:
                c.executemany("INSERT OR IGNORE INTO local_puzzles (id, fen, moves, rating, themes) VALUES (?, ?, ?, ?, ?)", batch)
                conn.commit()
                
    conn.close()
    print("Done! Local puzzles ready.")

if __name__ == "__main__":
    download_puzzles(50000)
