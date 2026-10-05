import httpx
import asyncio
import logging
import random
import chess.pgn
import io
from typing import Dict, Any
from pipeline.uniqueness import is_unique, get_variety_constraints, mark_used
from pipeline.ssl_context import get_ssl_context

logger = logging.getLogger(__name__)

FAMOUS_POSITIONS = [
    {
        "player": "Magnus Carlsen",
        "opponent": "Vishy Anand",
        "event": "World Championship",
        "year": 2013,
        "fen": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "moves": ["d2d4", "e5d4", "c4f7"],
        "tactic": "Brilliant sacrifice"
    },
    {
        "player": "Garry Kasparov",
        "opponent": "Deep Blue",
        "event": "Man vs Machine",
        "year": 1997,
        "fen": "rnbqkb1r/pp3ppp/2p5/3pP3/3Pn3/2N5/PP3PPP/R1BQKBNR w KQkq - 1 7",
        "moves": ["c3e4", "d5e4"],
        "tactic": "Center control"
    },
    {
        "player": "Bobby Fischer",
        "opponent": "Boris Spassky",
        "event": "World Championship",
        "year": 1972,
        "fen": "2rq1rk1/1p3ppp/p3bn2/2b5/3p4/P1N1P3/1P1BBPPP/R1Q2RK1 b - - 1 15",
        "moves": ["d4c3", "d2c3"],
        "tactic": "Pawn structure"
    },
    {
        "player": "Praggnanandhaa R",
        "opponent": "Magnus Carlsen",
        "event": "Meltwater Champions",
        "year": 2021,
        "fen": "r2q1rk1/pp2bppp/2n1pn2/2pp2B1/3P4/2P1P3/PP1N1PPP/R2Q1RK1 b - - 0 10",
        "moves": ["c5d4", "e3d4"],
        "tactic": "Solid setup"
    },
    {
        "player": "Hikaru Nakamura",
        "opponent": "Fabiano Caruana",
        "event": "Speed Chess Championship",
        "year": 2022,
        "fen": "r1bq1rk1/ppp1bppp/2n2n2/3p4/3P4/2NB1N2/PPP2PPP/R1BQ1RK1 w - - 4 8",
        "moves": ["h2h3", "h7h6"],
        "tactic": "Prophylaxis"
    },
    {
        "player": "Mikhail Tal",
        "opponent": "Dieter Keller",
        "event": "Zurich",
        "year": 1959,
        "fen": "r3k2r/1p3ppp/pqn1p3/3pP3/1b1P4/1PNQPN2/P5PP/R4RK1 w kq - 1 15",
        "moves": ["a2a3", "b4e7", "b3b4"],
        "tactic": "Queenside attack"
    },
    {
        "player": "Paul Morphy",
        "opponent": "Duke Karl",
        "event": "Opera Game",
        "year": 1858,
        "fen": "r3kb1r/p4ppp/1qp1p3/3pPb2/3P4/5N2/PP3PPP/RNBQ1RK1 b kq - 0 10",
        "moves": ["f8e7", "b1c3", "e8g8"],
        "tactic": "Development"
    },
    {
        "player": "Viswanathan Anand",
        "opponent": "Levon Aronian",
        "event": "Tata Steel",
        "year": 2013,
        "fen": "r2qr1k1/pp3ppp/2n2n2/3p4/1b1P2b1/2NB1N2/PP3PPP/R1BQR1K1 w - - 6 12",
        "moves": ["c1e3", "f6e4", "d1b3"],
        "tactic": "Dynamic equality"
    },
    {
        "player": "Ding Liren",
        "opponent": "Ian Nepomniachtchi",
        "event": "World Championship",
        "year": 2023,
        "fen": "r3r1k1/pp1n1ppp/2p2n2/3p4/1b1P2b1/2NB1N2/PPPB1PPP/R4RK1 b - - 8 13",
        "moves": ["g4f3", "g2f3"],
        "tactic": "Structure damage"
    },
    {
        "player": "Fabiano Caruana",
        "opponent": "Maxime Vachier-Lagrave",
        "event": "Sinquefield Cup",
        "year": 2014,
        "fen": "r2q1rk1/pp1nbppp/2p1pn2/3p4/2PP4/1PNQPN2/P4PPP/R1B2RK1 b - - 0 10",
        "moves": ["d5c4", "b3c4", "e6e5"],
        "tactic": "Central break"
    },
    {
        "player": "Alireza Firouzja",
        "opponent": "Magnus Carlsen",
        "event": "Norway Chess",
        "year": 2020,
        "fen": "r2q1rk1/pp1bbppp/2n1pn2/3p4/2PP4/1PN2N2/PB2BPPP/R2Q1RK1 b - - 2 11",
        "moves": ["f6e4", "c4d5", "e4c3"],
        "tactic": "Outpost"
    },
    {
        "player": "Anatoly Karpov",
        "opponent": "Viktor Korchnoi",
        "event": "World Championship",
        "year": 1978,
        "fen": "r1bq1rk1/pp1nbppp/2p1pn2/3p4/2PP4/1PN1PN2/PB3PPP/R2QKB1R w KQ - 3 9",
        "moves": ["f1d3", "d5c4", "b3c4"],
        "tactic": "Space advantage"
    },
    {
        "player": "Levon Aronian",
        "opponent": "Vladimir Kramnik",
        "event": "Candidates",
        "year": 2014,
        "fen": "r2q1rk1/1p2bppp/p1np1n2/4p1B1/4P3/1NN5/PPP2PPP/R2Q1RK1 w - - 4 12",
        "moves": ["g5f6", "e7f6", "c3d5"],
        "tactic": "Strong knight"
    },
    {
        "player": "Maxime Vachier-Lagrave",
        "opponent": "Magnus Carlsen",
        "event": "Sinquefield Cup",
        "year": 2017,
        "fen": "r1bq1rk1/1p2bppp/p1nppn2/8/3NPP2/2N1B3/PPP1B1PP/R2Q1RK1 w - - 1 10",
        "moves": ["d1e1", "c6xd4", "e3xd4"],
        "tactic": "Sicilian defense"
    },
    {
        "player": "Vladimir Kramnik",
        "opponent": "Garry Kasparov",
        "event": "World Championship",
        "year": 2000,
        "fen": "r2q1rk1/1pp2ppp/p1nbpn2/3p4/3P4/1QP1PNB1/PP3PPP/RN2K2R b KQ - 2 10",
        "moves": ["f6e4", "b3xb7", "c6a5"],
        "tactic": "Trapped piece"
    },
    {
        "player": "Wesley So",
        "opponent": "Magnus Carlsen",
        "event": "Fischer Random",
        "year": 2019,
        "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        "moves": ["e2e4", "e7e5", "g1f3"],
        "tactic": "Opening principles"
    },
    {
        "player": "Ian Nepomniachtchi",
        "opponent": "Ding Liren",
        "event": "Candidates",
        "year": 2020,
        "fen": "r1bq1rk1/pp1n1ppp/2pbpn2/3p4/2PP4/1PN1PN2/PB2BPPP/R2Q1RK1 b - - 4 10",
        "moves": ["d5c4", "b3c4", "e6e5"],
        "tactic": "Pawn break"
    },
    {
        "player": "Daniil Dubov",
        "opponent": "Sergey Karjakin",
        "event": "Russian Championship",
        "year": 2020,
        "fen": "r2q1rk1/pp1nbppp/2p1pn2/3p4/2PP4/1PN1PN2/P4PPP/R1BQ1RK1 w - - 1 10",
        "moves": ["d1c2", "d5c4", "b3c4"],
        "tactic": "Queen placement"
    },
    {
        "player": "Alexander Grischuk",
        "opponent": "Peter Svidler",
        "event": "Candidates",
        "year": 2013,
        "fen": "r1bq1rk1/ppp1bppp/2n1pn2/3p4/2PP4/1PN2N2/PB2PPPP/R2QKB1R w KQ - 3 8",
        "moves": ["e2e3", "a7a6", "a1c1"],
        "tactic": "Solid structure"
    },
    {
        "player": "Anish Giri",
        "opponent": "Magnus Carlsen",
        "event": "Tata Steel",
        "year": 2011,
        "fen": "r2q1rk1/pp1nbppp/2p1pn2/3p4/2PP4/1PN1PN2/PB3PPP/R2Q1RK1 b - - 4 10",
        "moves": ["d5c4", "b3c4", "c6c5"],
        "tactic": "Challenging the center"
    }
]

USER_AGENT = "KnightifyChessShorts/1.0 (+https://github.com/HarishkannaR11/Chess-Shorts)"

# Where to pull each champion's recent games from. Usernames are per site:
# the same player usually has different Lichess and chess.com handles.
GAME_SOURCES = [
    {"player": "Magnus Carlsen", "site": "lichess", "user": "DrNykterstein"},
    {"player": "Magnus Carlsen", "site": "chesscom", "user": "MagnusCarlsen"},
    {"player": "Hikaru Nakamura", "site": "chesscom", "user": "Hikaru"},
    {"player": "Praggnanandhaa R", "site": "chesscom", "user": "rpragchess"},
    {"player": "Alireza Firouzja", "site": "chesscom", "user": "AlirezaFirouzja"},
    {"player": "Alireza Firouzja", "site": "lichess", "user": "alireza2003"},
    {"player": "Daniel Naroditsky", "site": "chesscom", "user": "DanielNaroditsky"},
    {"player": "Nihal Sarin", "site": "chesscom", "user": "nihalsarin"},
    {"player": "Fabiano Caruana", "site": "chesscom", "user": "FabianoCaruana"},
    {"player": "Gukesh D", "site": "chesscom", "user": "GukeshDommaraju"},
]

async def _fetch_recent_games(client: httpx.AsyncClient, source: dict) -> list:
    """Recent games for a source as [{"pgn", "event"}]. Raises on HTTP errors."""
    if source["site"] == "lichess":
        resp = await client.get(
            f"https://lichess.org/api/games/user/{source['user']}",
            params={"max": 100, "rated": "true"},
            headers={"Accept": "application/x-chess-pgn"},
        )
        resp.raise_for_status()
        return [{"pgn": p, "event": None} for p in resp.text.strip().split("\n\n\n") if p.strip()]

    # chess.com: monthly archives, newest last. Keep only wins by checkmate.
    resp = await client.get(f"https://api.chess.com/pub/player/{source['user'].lower()}/games/archives")
    resp.raise_for_status()
    games = []
    for url in reversed(resp.json().get("archives", [])[-3:]):
        month = await client.get(url)
        month.raise_for_status()
        for g in month.json().get("games", []):
            if g.get("rules") != "chess" or "pgn" not in g:
                continue
            champ = "white" if g["white"].get("username", "").lower() == source["user"].lower() else "black"
            other = "black" if champ == "white" else "white"
            if g[champ].get("result") == "win" and g[other].get("result") == "checkmated":
                games.append({"pgn": g["pgn"], "event": f"{g.get('time_class', 'online').capitalize()} game on Chess.com"})
    return games

def _extract_finish(pgn_text: str, source: dict, extract_len: int = 12) -> Dict[str, Any] | None:
    """The last `extract_len` plies of a game the champion won by checkmate, else None."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        return None
    moves = list(game.mainline_moves())
    if len(moves) < 20:
        return None

    white = game.headers.get("White", "Unknown")
    black = game.headers.get("Black", "Unknown")
    user = source["user"].lower()
    if user not in (white.lower(), black.lower()):
        return None
    champ_color = chess.WHITE if white.lower() == user else chess.BLACK

    board = game.board()
    for m in moves:
        board.push(m)
    # After mate it's the mated side's turn: make sure that's not the champion
    if not board.is_checkmate() or board.turn == champ_color:
        return None

    start_ply = len(moves) - extract_len
    start_board = game.board()
    for m in moves[:start_ply]:
        start_board.push(m)
    date = game.headers.get("Date", "")
    return {
        "fen": start_board.fen(),
        "moves": [m.uci() for m in moves[start_ply:]],
        "opponent": black if champ_color == chess.WHITE else white,
        "year": date.split(".")[0] if "." in date else "2023",
        "event": game.headers.get("Event", "Online game"),
    }

async def fetch_champion_game(target_player: str = None, allow_fallback: bool = True) -> Dict[str, Any]:
    """
    Fetch the checkmating finish of a real champion game from Lichess or
    chess.com (hardcoded famous positions only if allow_fallback).
    Guarantees uniqueness through pipeline.uniqueness module.
    """
    constraints = get_variety_constraints()
    avoid_player = constraints.get("avoid_player")

    # Requested player first, then everyone else (skipping the last player used)
    preferred = [s for s in GAME_SOURCES if s["player"] == target_player]
    others = [s for s in GAME_SOURCES if s not in preferred and s["player"] != avoid_player]
    random.shuffle(preferred)
    random.shuffle(others)

    backed_off = False
    async with httpx.AsyncClient(verify=get_ssl_context(), timeout=30, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        for source in preferred + others:
            label = f"{source['player']} ({source['site']}: {source['user']})"
            try:
                games = await _fetch_recent_games(client, source)
            except httpx.HTTPStatusError as e:
                logger.warning(f"Could not fetch games for {label}: HTTP {e.response.status_code}")
                if e.response.status_code == 429 and not backed_off:
                    # Both sites ask clients to wait a minute after a 429
                    backed_off = True
                    await asyncio.sleep(60)
                continue
            except Exception as e:
                logger.warning(f"Could not fetch games for {label}: {e}")
                continue

            random.shuffle(games)
            for g in games:
                finish = _extract_finish(g["pgn"], source)
                if not finish or not is_unique(finish["fen"]):
                    continue
                tactic = "Checkmate sequence"
                mark_used(finish["fen"], source["player"], tactic)
                return {
                    "fen": finish["fen"],
                    "moves": finish["moves"],
                    "player": source["player"],
                    "opponent": finish["opponent"],
                    "event": g["event"] or finish["event"],
                    "year": finish["year"],
                    "tactic": tactic,
                    "rating": 2800,
                    "themes": ["tactics", "live_game"],
                    "source": source["site"],
                }
            logger.info(f"No new checkmate finishes in {len(games)} recent games of {label}")
                
    # Fallback if loop fails
    if not allow_fallback:
        raise RuntimeError("Could not fetch a unique checkmate game from Lichess or chess.com.")
    game = random.choice(FAMOUS_POSITIONS)
    return {
        "fen": game["fen"],
        "moves": game["moves"],
        "player": game["player"],
        "opponent": game["opponent"],
        "event": game["event"],
        "year": game["year"],
        "tactic": game["tactic"],
        "rating": 2800,
        "themes": [game["tactic"].lower().replace(" ", "_")],
        "source": "hardcoded_fallback"
    }
