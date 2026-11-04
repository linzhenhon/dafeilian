"""Persistent local Whisper worker for the desktop pet's microphone input.

JSON lines on stdin and stdout keep model loading outside the Qt process. The
worker reads one short WAV segment at a time; the caller deletes each file.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import warnings


# Keep a small dependency-free safety net for bare Python environments. Full
# conversion uses OpenCC below; these common Whisper characters also keep short
# dictation readable if the optional converter cannot be imported at runtime.
_BASIC_TRADITIONAL_TO_SIMPLIFIED = str.maketrans({
    "務": "务",
    "質": "质",
    "點": "点",
    "審": "审",
})


def max_tokens_for_audio(seconds: float) -> int:
    """Bound decoding to the length of a short recorded utterance."""
    return min(256, max(48, math.ceil(seconds * 14)))


def implausible_transcript(text: str, seconds: float) -> bool:
    """Reject obvious Whisper loops before they reach a task input or call."""
    compact = re.sub(r"[^\w]+", "", text, flags=re.UNICODE)
    if len(compact) > max(48, math.ceil(seconds * 20)):
        return True
    return re.search(r"(.{4,40}?)\1{2,}", compact) is not None


def simplify_chinese(text: str) -> str:
    """Normalize Whisper's Chinese output to simplified characters."""
    if not text:
        return text
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        mapper = ctypes.windll.kernel32.LCMapStringEx
        mapper.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR, ctypes.c_int,
            wintypes.LPWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.LPARAM,
        ]
        mapper.restype = ctypes.c_int
        flags = 0x02000000  # LCMAP_SIMPLIFIED_CHINESE
        length = mapper("zh-CN", flags, text, -1, None, 0, None, None, 0)
        if length:
            output = ctypes.create_unicode_buffer(length)
            if mapper("zh-CN", flags, text, -1, output, length, None, None, 0):
                return output.value
    else:
        try:
            from opencc import OpenCC
        except ImportError:
            return text.translate(_BASIC_TRADITIONAL_TO_SIMPLIFIED)
        return OpenCC("t2s").convert(text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="openai/whisper-base")
    args = parser.parse_args()
    recognizer = None
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            if recognizer is None:
                import torch
                from transformers import pipeline

                torch.set_num_threads(min(4, max(1, torch.get_num_threads())))
                recognizer = pipeline("automatic-speech-recognition", model=args.model, device=-1)
            if request.get("warm") is True:
                print(json.dumps({"id": request_id, "text": ""}), flush=True)
                continue
            path = request["path"]
            import numpy as np
            import soundfile as sf
            from scipy.signal import resample_poly

            samples, rate = sf.read(path, dtype="float32")
            if samples.ndim == 2:
                samples = samples.mean(axis=1)
            if rate != 16000:
                from math import gcd

                factor = gcd(rate, 16000)
                samples = resample_poly(samples, 16000 // factor, rate // factor)
            duration_s = len(samples) / 16000
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                result = recognizer(
                    {"array": np.asarray(samples, dtype=np.float32), "sampling_rate": 16000},
                    generate_kwargs={
                        "language": "zh",
                        "task": "transcribe",
                        "num_beams": 2,
                        "no_repeat_ngram_size": 4,
                        "max_new_tokens": max_tokens_for_audio(duration_s),
                    },
                )
            text = str(result.get("text", "")).strip()
            reply = {"id": request_id, "text": "" if implausible_transcript(text, duration_s) else simplify_chinese(text)}
        except Exception as error:
            reply = {"id": request.get("id") if isinstance(request, dict) else None, "error": str(error)[:300]}
        print(json.dumps(reply, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
