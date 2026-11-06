import time
import unittest
from threading import Event

from runtime.xiangqi import (
    ADVISOR, BLACK, CANNON, ELEPHANT, Game, HORSE, KING, Move, PAWN, RED, ROOK,
    apply_move, choose_move, in_check, initial_board, legal_moves, pseudo_targets,
)


def position(pieces):
    board = [0] * 90
    for x, y, piece in pieces:
        board[y * 9 + x] = piece
    return tuple(board)


class XiangqiRulesTests(unittest.TestCase):
    def test_initial_position_and_moves(self):
        board = initial_board()
        self.assertEqual(len(board), 90)
        self.assertEqual(sum(bool(piece) for piece in board), 32)
        self.assertEqual(len(legal_moves(board, RED)), 44)
        self.assertEqual(len(legal_moves(board, BLACK)), 44)
        self.assertFalse(in_check(board, RED))
        self.assertFalse(in_check(board, BLACK))

    def test_cannon_needs_exactly_one_screen_to_capture(self):
        board = position([(4, 7, CANNON), (4, 5, PAWN), (4, 2, -ROOK), (4, 0, -HORSE)])
        moves = set(pseudo_targets(board, 7 * 9 + 4))
        self.assertIn(2 * 9 + 4, moves)
        self.assertIn(6 * 9 + 4, moves)
        self.assertNotIn(4 * 9 + 4, moves)
        self.assertNotIn(4, moves)
        board = position([(4, 7, CANNON), (4, 2, -ROOK)])
        self.assertNotIn(2 * 9 + 4, set(pseudo_targets(board, 7 * 9 + 4)))

    def test_horse_leg_elephant_eye_and_river(self):
        board = position([(4, 6, HORSE), (4, 5, PAWN)])
        targets = set(pseudo_targets(board, 6 * 9 + 4))
        self.assertNotIn(4 * 9 + 3, targets)
        self.assertNotIn(4 * 9 + 5, targets)
        self.assertIn(8 * 9 + 3, targets)
        board = position([(4, 7, ELEPHANT), (3, 6, PAWN)])
        self.assertNotIn(5 * 9 + 2, set(pseudo_targets(board, 7 * 9 + 4)))
        board = position([(4, 5, ELEPHANT)])
        self.assertNotIn(3 * 9 + 2, set(pseudo_targets(board, 5 * 9 + 4)))

    def test_palace_and_pawn_direction_for_both_sides(self):
        for side, row in ((RED, 7), (BLACK, 2)):
            for kind in (KING, ADVISOR):
                board = position([(4, row, side * kind)])
                for target in pseudo_targets(board, row * 9 + 4):
                    self.assertTrue(3 <= target % 9 <= 5)
                    self.assertTrue(target // 9 >= 7 if side == RED else target // 9 <= 2)
        for side, before, after in ((RED, 6, 4), (BLACK, 3, 5)):
            board = position([(4, before, side * PAWN)])
            self.assertEqual(set(pseudo_targets(board, before * 9 + 4)), {(before - side) * 9 + 4})
            board = position([(4, after, side * PAWN)])
            self.assertEqual(len(list(pseudo_targets(board, after * 9 + 4))), 3)
            self.assertNotIn((after + side) * 9 + 4, set(pseudo_targets(board, after * 9 + 4)))

    def test_general_face_and_self_check_are_illegal(self):
        board = position([(4, 9, KING), (4, 0, -KING), (4, 5, ROOK)])
        self.assertFalse(in_check(board, RED))
        self.assertNotIn(Move(5 * 9 + 4, 5 * 9 + 3), legal_moves(board, RED))
        exposed = apply_move(board, Move(5 * 9 + 4, 5 * 9 + 3))
        self.assertTrue(in_check(exposed, RED))
        self.assertTrue(in_check(exposed, BLACK))
        board = position([(4, 9, KING), (3, 0, -KING), (4, 0, -ROOK)])
        self.assertTrue(in_check(board, RED))
        for move in legal_moves(board, RED):
            self.assertFalse(in_check(apply_move(board, move), RED))

    def test_checkmate_and_stalemate_both_lose(self):
        for checked in (True, False):
            game = Game()
            game.board = position([(4, 0, -KING), (4, 9, KING), (4, 5, PAWN),
                                   (3, 1, ROOK), (5, 1, ROOK), (4, 3, ROOK) if checked else (0, 6, PAWN)])
            self.assertTrue(game.play(Move(31, 22) if checked else Move(54, 45)))
            self.assertEqual(game.winner, RED)
            self.assertEqual(game.reason, '将死' if checked else '困毙')

    def test_game_turns_repetition_and_round_undo(self):
        game = Game()
        self.assertFalse(game.play(Move(0, 9)), 'red moves first')
        self.assertTrue(game.play(Move(54, 45)))
        self.assertEqual(game.turn, BLACK)
        game.undo_round()
        self.assertEqual(game.board, initial_board())
        game.play(Move(54, 45))
        game.play(Move(27, 36))
        game.undo_round()
        self.assertEqual(game.board, initial_board())
        cycle = [Move(82, 63), Move(1, 18), Move(63, 82), Move(18, 1)]
        for move in cycle * 2:
            self.assertTrue(game.play(move))
        self.assertEqual(game.winner, 0)
        self.assertFalse(game.play(Move(54, 45)))
        game.undo_round()
        self.assertIsNone(game.winner)
        self.assertEqual(game.turn, RED)

    def test_local_opponent_is_legal_bounded_and_cancellable(self):
        game = Game()
        start = time.monotonic()
        for _ in range(4):
            move = choose_move(game.board, game.turn, seconds=0.06)
            self.assertIn(move, legal_moves(game.board, game.turn))
            self.assertTrue(game.play(move))
        self.assertLess(time.monotonic() - start, 2)
        cancel = Event()
        cancel.set()
        self.assertIsNone(choose_move(game.board, game.turn, cancel=cancel))


if __name__ == '__main__':
    unittest.main()
