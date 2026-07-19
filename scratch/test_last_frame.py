import asyncio
import chess
from pipeline.board import generate_frames

def main():
    fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
    moves = ["d8h4"]
    res = generate_frames(fen, moves, section_times=[])
    frames = res["frames"]
    # copy the last frame to scratch/last_frame.png
    import shutil
    shutil.copy(frames[-1], "scratch/last_frame.png")
    print(f"Copied {frames[-1]} to scratch/last_frame.png. Total frames: {len(frames)}")

if __name__ == "__main__":
    main()
