import unittest

from runtime.voice_worker import implausible_transcript, max_tokens_for_audio, simplify_chinese


class VoiceWorkerQualityTests(unittest.TestCase):
    def test_token_budget_tracks_audio_duration(self):
        self.assertEqual(max_tokens_for_audio(3.1), 48)
        self.assertEqual(max_tokens_for_audio(10), 140)
        self.assertEqual(max_tokens_for_audio(30), 256)

    def test_rejects_repeated_hallucination_from_short_clip(self):
        text = "质量有点冷。" + "你具有天文。" * 30
        self.assertTrue(implausible_transcript(text, 3.1))

    def test_keeps_short_spoken_instruction(self):
        self.assertFalse(implausible_transcript("大哥，请打开当前项目并检查测试结果。", 3.1))

    def test_simplifies_recognized_chinese(self):
        self.assertEqual(
            simplify_chinese("大哥，任務已完成。質量有點冷，等待大哥審批。"),
            "大哥，任务已完成。质量有点冷，等待大哥审批。",
        )
        self.assertEqual(simplify_chinese("发送 DSH task 123 😀"), "发送 DSH task 123 😀")


if __name__ == "__main__":
    unittest.main()
