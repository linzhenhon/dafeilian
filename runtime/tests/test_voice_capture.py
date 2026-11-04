import unittest
from array import array

from runtime.voice_capture import Pcm16MonoConverter, VoiceSegmenter


class Pcm16MonoConverterTests(unittest.TestCase):
    def test_native_16khz_mono_is_preserved(self):
        converter = Pcm16MonoConverter(16000, 1)
        source = array('h', [1200, -900, 0, 32767]).tobytes()
        self.assertEqual(converter.feed(source), source)

    def test_48khz_stereo_is_mixed_and_resampled(self):
        converter = Pcm16MonoConverter(48000, 2)
        stereo = array('h')
        for _ in range(4800):
            stereo.extend((2000, 1000))
        converted = converter.feed(stereo.tobytes())
        self.assertEqual(len(converted), 1600 * 2)
        output = array('h')
        output.frombytes(converted)
        self.assertEqual(set(output), {1500})

    def test_partial_device_frames_are_buffered(self):
        converter = Pcm16MonoConverter(16000, 2)
        source = array('h', [1000, 3000, -2000, 2000]).tobytes()
        self.assertEqual(converter.feed(source[:3]), b'')
        converted = converter.feed(source[3:])
        output = array('h')
        output.frombytes(converted)
        self.assertEqual(output.tolist(), [2000, 0])


class VoiceSegmenterTests(unittest.TestCase):
    def test_silence_completes_a_spoken_utterance(self):
        segmenter = VoiceSegmenter()
        quiet = bytes(VoiceSegmenter.FRAME_BYTES)
        speech = array('h', [1800] * (VoiceSegmenter.FRAME_BYTES // 2)).tobytes()
        self.assertEqual(segmenter.feed(quiet * 4), [])
        self.assertEqual(segmenter.feed(speech * 5), [])
        chunks = segmenter.feed(quiet * 8)
        self.assertEqual(len(chunks), 1)
        self.assertIn(speech, chunks[0])
        self.assertLess(len(segmenter.frames), 4)

    def test_noise_is_ignored_and_long_speech_is_split(self):
        segmenter = VoiceSegmenter(max_frames=8)
        quiet = bytes(VoiceSegmenter.FRAME_BYTES)
        speech = array('h', [1800] * (VoiceSegmenter.FRAME_BYTES // 2)).tobytes()
        self.assertEqual(segmenter.feed(speech + quiet * 8), [])
        self.assertEqual(len(segmenter.feed(speech * 12)), 1)
        self.assertIsNotNone(segmenter.flush())

    def test_short_confirmation_is_kept(self):
        segmenter = VoiceSegmenter()
        quiet = bytes(VoiceSegmenter.FRAME_BYTES)
        speech = array('h', [1800] * (VoiceSegmenter.FRAME_BYTES // 2)).tobytes()
        self.assertEqual(len(segmenter.feed(speech * 2 + quiet * 8)), 1)

    def test_live_meter_tracks_completed_audio_frames(self):
        segmenter = VoiceSegmenter()
        speech = array('h', [1800] * (VoiceSegmenter.FRAME_BYTES // 2)).tobytes()
        self.assertEqual(segmenter.feed(speech[:100]), [])
        self.assertEqual(segmenter.meter_frames, 0)
        segmenter.feed(speech[100:])
        self.assertEqual(segmenter.meter_frames, 1)
        self.assertAlmostEqual(segmenter.recent_energy, 1800)
        self.assertTrue(segmenter.recent_talking)
        segmenter.feed(bytes(VoiceSegmenter.FRAME_BYTES))
        self.assertEqual(segmenter.recent_energy, 0)
        self.assertFalse(segmenter.recent_talking)


if __name__ == '__main__':
    unittest.main()
