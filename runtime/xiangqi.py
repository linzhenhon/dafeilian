"""Dependency-free Xiangqi rules and a bounded local search opponent."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import monotonic

RED, BLACK = 1, -1
KING, ADVISOR, ELEPHANT, HORSE, ROOK, CANNON, PAWN = range(1, 8)
VALUES = {KING: 100000, ADVISOR: 200, ELEPHANT: 200, HORSE: 410, ROOK: 900, CANNON: 450, PAWN: 100}
ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
HORSE_STEPS = ((-2, -1), (-2, 1), (2, -1), (2, 1), (-1, -2), (1, -2), (-1, 2), (1, 2))


@dataclass(frozen=True)
class Move:
    source: int
    target: int


def inside(x: int, y: int) -> bool:
    return 0 <= x < 9 and 0 <= y < 10


def palace(x: int, y: int, side: int) -> bool:
    return 3 <= x <= 5 and (7 <= y <= 9 if side == RED else 0 <= y <= 2)


def crossed(y: int, side: int) -> bool:
    return y <= 4 if side == RED else y >= 5


def initial_board() -> tuple[int, ...]:
    board = [0] * 90
    back = (ROOK, HORSE, ELEPHANT, ADVISOR, KING, ADVISOR, ELEPHANT, HORSE, ROOK)
    for x, piece in enumerate(back):
        board[x], board[81 + x] = -piece, piece
    for x in (1, 7):
        board[18 + x], board[63 + x] = -CANNON, CANNON
    for x in (0, 2, 4, 6, 8):
        board[27 + x], board[54 + x] = -PAWN, PAWN
    return tuple(board)


def apply_move(board: tuple[int, ...], move: Move) -> tuple[int, ...]:
    result = list(board)
    result[move.target], result[move.source] = result[move.source], 0
    return tuple(result)


def pseudo_targets(board: tuple[int, ...], source: int):
    piece = board[source]
    if not piece:
        return
    side, kind = (RED if piece > 0 else BLACK), abs(piece)
    x, y = source % 9, source // 9
    if kind in (ROOK, CANNON):
        for dx, dy in ORTHOGONAL:
            nx, ny, screen = x + dx, y + dy, False
            while inside(nx, ny):
                target, occupant = ny * 9 + nx, board[ny * 9 + nx]
                if not screen:
                    if not occupant:
                        yield target
                    else:
                        if kind == ROOK:
                            if occupant * side < 0:
                                yield target
                            break
                        screen = True
                elif occupant:
                    if occupant * side < 0:
                        yield target
                    break
                nx, ny = nx + dx, ny + dy
        return
    if kind == HORSE:
        steps = HORSE_STEPS
    elif kind == ELEPHANT:
        steps = ((-2, -2), (-2, 2), (2, -2), (2, 2))
    elif kind == ADVISOR:
        steps = ((-1, -1), (-1, 1), (1, -1), (1, 1))
    elif kind == KING:
        steps = ORTHOGONAL
        ny = y - side
        while 0 <= ny < 10:
            target = ny * 9 + x
            if board[target]:
                if board[target] == -side * KING:
                    yield target
                break
            ny -= side
    else:
        steps = ((0, -side), (-1, 0), (1, 0)) if crossed(y, side) else ((0, -side),)
    for dx, dy in steps:
        nx, ny = x + dx, y + dy
        if not inside(nx, ny) or board[ny * 9 + nx] * side > 0:
            continue
        if kind in (KING, ADVISOR) and not palace(nx, ny, side):
            continue
        if kind == HORSE:
            lx, ly = (x + dx // 2, y) if abs(dx) == 2 else (x, y + dy // 2)
            if board[ly * 9 + lx]:
                continue
        if kind == ELEPHANT:
            if crossed(ny, side) or board[(y + dy // 2) * 9 + x + dx // 2]:
                continue
        yield ny * 9 + nx


def in_check(board: tuple[int, ...], side: int) -> bool:
    try:
        king = board.index(side * KING)
    except ValueError:
        return True
    x, y = king % 9, king // 9
    for dx, dy in ORTHOGONAL:
        nx, ny, occupied = x + dx, y + dy, 0
        while inside(nx, ny):
            piece = board[ny * 9 + nx]
            if piece:
                if occupied == 0 and piece * side < 0 and (abs(piece) == ROOK or (dx == 0 and abs(piece) == KING)):
                    return True
                if occupied == 1:
                    if piece == -side * CANNON:
                        return True
                    break
                occupied += 1
            nx, ny = nx + dx, ny + dy
    for square, piece in enumerate(board):
        if piece * side < 0 and abs(piece) in (HORSE, PAWN, ADVISOR, ELEPHANT):
            if king in pseudo_targets(board, square):
                return True
    return False


def legal_moves(board: tuple[int, ...], side: int) -> list[Move]:
    if side * KING not in board:
        return []
    return [Move(source, target) for source, piece in enumerate(board) if piece * side > 0
            for target in pseudo_targets(board, source)
            if not in_check(apply_move(board, Move(source, target)), side)]


class Game:
    def __init__(self) -> None:
        self.board = initial_board()
        self.turn = RED
        self.history: list[tuple[tuple[int, ...], int, Move]] = []
        self.winner: int | None = None  # 0 is a draw.
        self.reason = ""

    @property
    def last_move(self) -> Move | None:
        return self.history[-1][2] if self.history else None

    def play(self, move: Move) -> bool:
        if self.winner is not None or move not in legal_moves(self.board, self.turn):
            return False
        self.history.append((self.board, self.turn, move))
        self.board = apply_move(self.board, move)
        self.turn = -self.turn
        if not legal_moves(self.board, self.turn):
            self.winner = -self.turn
            self.reason = "将死" if in_check(self.board, self.turn) else "困毙"
        elif sum(board == self.board and turn == self.turn for board, turn, _ in self.history) >= 2:
            self.winner, self.reason = 0, "三次重复局面，和棋"
        return True

    def undo_round(self) -> None:
        count = 2 if self.turn == RED else 1
        for _ in range(min(count, len(self.history))):
            self.board, self.turn, _ = self.history.pop()
        self.winner, self.reason = None, ""


def evaluate(board: tuple[int, ...], side: int) -> int:
    score = 0
    for square, piece in enumerate(board):
        if not piece:
            continue
        owner, kind = (RED if piece > 0 else BLACK), abs(piece)
        x, y = square % 9, square // 9
        advance = 9 - y if owner == RED else y
        bonus = 0
        if kind == PAWN:
            bonus = advance * 7 + (90 + (4 - abs(x - 4)) * 7 if crossed(y, owner) else 0)
        elif kind in (HORSE, CANNON, ROOK):
            bonus = (4 - abs(x - 4)) * 6 + min(advance, 6) * 3
        score += owner * (VALUES[kind] + bonus)
    return score * side


class SearchStopped(Exception):
    pass


def choose_move(board: tuple[int, ...], side: int, *, seconds: float = 0.8,
                max_depth: int = 3, cancel: Event | None = None) -> Move | None:
    deadline = monotonic() + seconds

    def check_time():
        if monotonic() >= deadline or (cancel is not None and cancel.is_set()):
            raise SearchStopped

    def ordered(position, moves, preferred=None):
        return sorted(moves, key=lambda m: (m == preferred, abs(position[m.target]) == KING,
                      VALUES.get(abs(position[m.target]), 0) * 10 - VALUES[abs(position[m.source])]), reverse=True)

    def quiet_search(position, player, alpha, beta, remaining, ply):
        check_time()
        if player * KING not in position:
            return -1000000 + ply
        checked = in_check(position, player)
        value = evaluate(position, player)
        if not checked:
            if value >= beta or remaining == 0:
                return value
            alpha = max(alpha, value)
            moves = [Move(source, target) for source, piece in enumerate(position) if piece * player > 0
                     for target in pseudo_targets(position, source) if position[target] * player < 0
                     and not in_check(apply_move(position, Move(source, target)), player)]
        else:
            moves = legal_moves(position, player)
            if not moves:
                return -1000000 + ply
            if remaining == 0:
                return value
        for move in ordered(position, moves):
            value = -quiet_search(apply_move(position, move), -player, -beta, -alpha, remaining - 1, ply + 1)
            if value >= beta:
                return value
            alpha = max(alpha, value)
        return alpha

    def search(position, player, depth, alpha, beta, ply):
        check_time()
        if player * KING not in position:
            return -1000000 + ply
        if depth == 0:
            return quiet_search(position, player, alpha, beta, 4, ply)
        moves = legal_moves(position, player)
        if not moves:
            return -1000000 + ply
        value = -2000000
        for move in ordered(position, moves):
            result = -search(apply_move(position, move), -player, depth - 1, -beta, -alpha, ply + 1)
            value, alpha = max(value, result), max(alpha, result)
            if alpha >= beta:
                break
        return value

    moves = legal_moves(board, side)
    if not moves or (cancel is not None and cancel.is_set()):
        return None
    best = ordered(board, moves)[0]
    for depth in range(1, max_depth + 1):
        candidate, alpha = best, -2000000
        try:
            for move in ordered(board, moves, best):
                check_time()
                value = -search(apply_move(board, move), -side, depth - 1, -2000000, -alpha, 1)
                if value > alpha:
                    candidate, alpha = move, value
        except SearchStopped:
            break
        best = candidate
    return None if cancel is not None and cancel.is_set() else best
