import asyncio
import chess
from pipeline.board import generate_frames

def test_mate():
    # Fool's mate
    fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
    moves = ["d8h4"]
    
    # Check if the move is legal
    b = chess.Board(fen)
    move = chess.Move.from_uci(moves[0])
    print("Legal moves:", list(b.legal_moves))
    print("Is move legal?", move in b.legal_moves)
    
    # Run generator
    print("Generating frames...")
    res = generate_frames(fen, moves, section_times=[])
    
    print("Total frames generated:", res["total_frames"])

if __name__ == "__main__":
    test_mate()
