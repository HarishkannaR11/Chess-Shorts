import asyncio
import os
import sys
import shutil

# Add workspace root to python path
sys.path.append(r"k:\chess\Chess-Shorts")

from pipeline.board import generate_flash_frames
from pipeline.video import get_video_duration

def main():
    # Known checkmate sequence
    fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
    moves = ["d8h4"]
    
    print("Generating flash frames for checkmate sequence...")
    res = generate_flash_frames(fen, moves, rating=1200, cta_text="Test CTA")
    
    frames = res["frames"]
    last_frame = frames[-1]
    
    out_dir = "outputs"
    os.makedirs(out_dir, exist_ok=True)
    test_out = os.path.join(out_dir, "test_checkmate_last_frame.png")
    shutil.copy(last_frame, test_out)
    
    print(f"Total frames: {len(frames)}")
    print(f"Last frame saved to {test_out}")
    print("Please verify visually that this frame contains the checkmate.")

if __name__ == "__main__":
    main()
