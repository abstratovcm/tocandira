"""Playing one game between two UHP engines, with random openings."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from .uhp import Engine, PlayerSpec, UhpError, game_state

ONGOING = ("NotStarted", "InProgress")


def random_opening(
    engine: Engine, plies: int, rng: random.Random, game_type: str = "Base+MLP"
) -> tuple[list[str], str]:
    """Random legal line of `plies` moves, using `engine` as the rules oracle.

    Returns (moves, game state after them); the engine is left at the end of the line.
    """
    state = game_state(engine.newgame(game_type))
    moves = []
    for _ in range(plies):
        move = rng.choice(engine.validmoves())
        moves.append(move)
        state = game_state(engine.play(move))
        if state not in ONGOING:
            break
    return moves, state


@dataclass
class GameRecord:
    """One finished game: who played, the full move list, result and timing."""

    white: str
    black: str
    game_type: str
    opening: list[str]
    moves: list[str]  # full move list, opening included
    # WhiteWins | BlackWins | Draw | ForfeitWhite | ForfeitBlack | PlyCap | Disagree
    # (Disagree: the two engines differ on whether the game ended, e.g. repetition rules).
    result: str
    plies: int
    white_time: float
    black_time: float
    wall: float
    error: str = ""

    def score_for_white(self) -> float:
        """1 for a white win, 0 for a black win, 0.5 for a draw or a ply cap."""
        if self.result in ("WhiteWins", "ForfeitBlack"):
            return 1.0
        if self.result in ("BlackWins", "ForfeitWhite"):
            return 0.0
        return 0.5


def play_game(
    white: PlayerSpec,
    black: PlayerSpec,
    opening: list[str],
    game_type: str = "Base+MLP",
    ply_cap: int = 300,
) -> GameRecord:
    """Play one game from `opening` and return its record.

    Both engines track the game; the harness sends every move to both and trusts the
    opponent's `play` to reject illegal moves (a rejected move forfeits).
    """
    t0 = time.perf_counter()
    engines = [Engine(white), Engine(black)]
    times = [0.0, 0.0]
    moves = list(opening)
    result, error = "PlyCap", ""
    try:
        state = "NotStarted"
        for e in engines:
            e.newgame(game_type)
        for m in opening:
            state = game_state(engines[0].play(m))
            engines[1].play(m)
        while state in ONGOING and len(moves) < ply_cap:
            side = len(moves) % 2  # white moves on even plies
            t = time.perf_counter()
            move = engines[side].bestmove()
            times[side] += time.perf_counter() - t
            try:
                state = game_state(engines[1 - side].play(move))
            except UhpError as exc:
                result = "ForfeitWhite" if side == 0 else "ForfeitBlack"
                error = str(exc)
                break
            own_state = game_state(engines[side].play(move))
            moves.append(move)
            if own_state != state:
                result = "Disagree"
                error = f"after {move}: mover says {own_state}, opponent says {state}"
                break
        else:
            if state not in ONGOING:
                result = state
    finally:
        for e in engines:
            e.close()
    return GameRecord(
        white=white.name,
        black=black.name,
        game_type=game_type,
        opening=opening,
        moves=moves,
        result=result,
        plies=len(moves),
        white_time=times[0],
        black_time=times[1],
        wall=time.perf_counter() - t0,
        error=error,
    )
