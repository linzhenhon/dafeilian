from __future__ import annotations

import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

from runtime.xiangqi import BLACK, KING, RED, ROOK, PAWN, Game, Move
from runtime.xiangqi_mode import XiangqiMode


class XiangqiSoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sounds: list[str] = []
        self.owner = SimpleNamespace(sound_enabled=True, _play_chess_sound=self.sounds.append)
        self.mode = XiangqiMode(self.owner)

    def test_move_and_capture_have_distinct_sound_events(self) -> None:
        quiet_move = Move(54, 45)
        self.assertTrue(self.mode.game.play(quiet_move))
        self.mode._play_move_sound(quiet_move)

        board = [0] * 90
        board[4] = -KING
        board[84] = KING
        board[39] = ROOK
        board[30] = -PAWN
        self.mode.game = Game()
        self.mode.game.board = tuple(board)
        capture = Move(39, 30)
        self.assertTrue(self.mode.game.play(capture))
        self.mode._play_move_sound(capture)

        self.assertEqual(self.sounds, ["move", "capture"])

    def test_check_and_game_end_have_distinct_sound_events(self) -> None:
        board = [0] * 90
        board[4] = -KING
        board[84] = KING
        board[40] = ROOK
        self.mode.game.board = tuple(board)
        check = Move(40, 13)
        self.assertTrue(self.mode.game.play(check))
        self.mode._play_move_sound(check)

        board = [0] * 90
        board[30] = -KING
        board[84] = KING
        board[39] = ROOK
        self.mode.game = Game()
        self.mode.game.board = tuple(board)
        win = Move(39, 30)
        self.assertTrue(self.mode.game.play(win))
        self.mode._play_move_sound(win)

        board = [0] * 90
        board[4] = -KING
        board[39] = KING
        board[30] = -ROOK
        self.mode.game = Game()
        self.mode.game.board = tuple(board)
        self.mode.game.turn = BLACK
        opponent_win = Move(30, 39)
        self.assertTrue(self.mode.game.play(opponent_win))
        self.mode._play_move_sound(opponent_win)

        self.assertEqual(self.sounds, ["check", "win", "loss"])

    def test_global_sound_switch_mutes_chess_and_wav_assets_are_packaged(self) -> None:
        self.owner.sound_enabled = False
        move = Move(54, 45)
        self.assertTrue(self.mode.game.play(move))
        self.mode._play_move_sound(move)
        self.assertEqual(self.sounds, [])

        root = Path(__file__).resolve().parents[2] / "assets" / "sounds" / "xiangqi"
        for name in ("move", "capture", "check", "win", "loss"):
            with wave.open(str(root / f"{name}.wav"), "rb") as sound:
                self.assertEqual(sound.getnchannels(), 1)
                self.assertEqual(sound.getsampwidth(), 2)
                self.assertEqual(sound.getframerate(), 44_100)
                self.assertGreater(sound.getnframes(), 2_000)


if __name__ == "__main__":
    unittest.main()
