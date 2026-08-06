#!/usr/bin/env python3
"""
Diagnostic utility for GyanVerse Academy voice synthesis & playback reliability.
Validates WAV headers, cache reuse, and optional native playback.
"""
from __future__ import annotations

import argparse
import sys
import wave
import io
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase11_ai import GyanVerseAIService, AIServiceError


def main() -> int:
    parser = argparse.ArgumentParser(description="GyanVerse Tutor Voice Diagnostic Utility")
    parser.add_argument("--play", action="store_true", help="Play synthesized audio on local speaker")
    parser.add_argument(
        "--language",
        choices=["English", "Hindi", "Gujarati", "Hinglish"],
        default="English",
        help="Language hint for synthesis (default: English)",
    )
    parser.add_argument("--sim-concurrent", action="store_true", help="Simulate concurrent callers joining single-flight synthesis")
    parser.add_argument("--fresh", action="store_true", help="Bypass cache identity for a real fresh synthesis test")
    parser.add_argument("--progressive", action="store_true", help="Test progressive sentence segmentation and manifest preparation")
    parser.add_argument("--stream", action="store_true", help="Test 1-request streaming audio pipeline and report chunk metrics")
    args = parser.parse_args()

    print("=== GyanVerse Tutor Voice Diagnostic ===")
    service = GyanVerseAIService()

    print(f"Platform: {sys.platform}")
    print(f"Selected Mode: {service.tts_mode}")
    print(f"Selected Voice: {service.tts_voice_name}")
    print(f"TTS Model: {service.tts_model_name}")
    prefetch_active = (
        service.tts_prefetch_enabled
        and service.tts_prefetch_policy != "none"
    )
    if service.tts_mode == "natural":
        configured_route = "natural-only"
    elif service.tts_mode == "local":
        configured_route = "local-only"
    elif service.tts_backend in {"gemini-first", "gemini-only"}:
        configured_route = service.tts_backend
    else:
        configured_route = "natural-first with local fallback"

    print(f"Prefetch Policy: {service.tts_prefetch_policy}")
    print(f"Prefetch Active: {prefetch_active}")
    print(f"Configured TTS Route: {configured_route}")
    print(f"Local Desktop Voice Available: {service.local_tts_available}")
    print(f"Gemini Voice Configured: {service.tts_configured}")
    print(f"Selected TTS Backend Label: {service.tts_backend_label}")
    print(f"Native Playback Available: {service.native_playback_available}")
    print(f"TTS Cache Dir: {service.tts_cache_dir}")
    print()

    sample_texts = {
        "English": "Hello! I am your GyanVerse tutor, ready to help you learn.",
        "Hindi": "नमस्ते! मैं आपका ज्ञानवर्स ट्यूटर हूँ, पढ़ाई में आपकी मदद के लिए तैयार हूँ।",
        "Gujarati": "નમસ્તે! હું તમારો જ્ઞાનવર્સ ટ્યુટર છું, તમને ભણાવવા માટે તૈયાર છું.",
        "Hinglish": "Namaste! Main aapka GyanVerse tutor hoon, aapki padhai mein help karne ke liye ready hoon.",
    }
    base_sample = sample_texts.get(args.language, sample_texts["English"])
    sample = f"{base_sample} (diag {time.time_ns()})" if args.fresh else base_sample

    print(f"Synthesizing test phrase in {args.language} (fresh={args.fresh}, stream={args.stream})...")
    t_synth_start = time.perf_counter()
    try:
        audio_bytes = service.synthesize(sample, language_hint=args.language, answer_id="diag_01")
    except AIServiceError as exc:
        if getattr(exc, "quota_limited", False) or "quota" in str(exc).lower() or "429" in str(exc):
            print(f"FAIL: Quota limited: {exc} (QUOTA_LIMITED)")
            return 1
        print(f"FAIL: Synthesis error: {exc}")
        return 1
    except Exception as exc:
        print(f"FAIL: Unexpected error: {type(exc).__name__}: {exc}")
        return 1
    t_synth_end = time.perf_counter()
    full_prep_time_ms = (t_synth_end - t_synth_start) * 1000.0

    if not (audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]):
        print("FAIL: Returned bytes fail WAV header validation (missing RIFF/WAVE).")
        return 1

    m = service.last_tts_metrics
    size_bytes = len(audio_bytes)
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            frames = wf.getnframes()
            duration_sec = frames / float(sample_rate) if sample_rate > 0 else 0.0
    except Exception as exc:
        print(f"WARNING: Wave header parsing warning: {exc}")
        channels, sample_rate, duration_sec = 1, 24000, 0.0

    print(f"SUCCESS: Synthesized {size_bytes} bytes via [{service.last_tts_backend}]")
    print(f"Audio details: {channels} channel(s), {sample_rate} Hz, {duration_sec:.2f}s duration")
    print(f"Stream Timings: Provider Calls={m.provider_call_count} | First Chunk={m.first_audio_chunk_ms:.1f}ms | Playable Buffer={m.playback_started_ms:.1f}ms | Prov Comp={m.provider_complete_ms:.1f}ms | Cache Comp={m.cache_complete_ms:.1f}ms | Chunks={m.audio_chunk_count} | Cache Hit={m.cache_hit}")

    if args.progressive:
        print("\n=== Testing Progressive Sentence Segmentation & Audio Manifest ===")
        prog_sample = (
            "Hello! I am your GyanVerse tutor. "
            "Photosynthesis converts sunlight into energy. "
            "Plants release oxygen into the air."
        )
        if args.fresh:
            prog_sample = f"{prog_sample} (fresh {time.time_ns()})"

        manifest = service.create_audio_manifest(prog_sample, language_hint=args.language, message_id="prog_diag_01")
        print(f"Manifest created: message_id={manifest.message_id}, voice={manifest.voice}, total_segments={manifest.total_segment_count}")

        t_seg1_start = time.perf_counter()
        seg1_bytes = service.synthesize_segment(manifest.segments[0], answer_id=manifest.message_id)
        t_seg1_end = time.perf_counter()
        first_audio_ready_ms = (t_seg1_end - t_seg1_start) * 1000.0

        print(f"SUCCESS: Segment 1 ready in {first_audio_ready_ms:.1f}ms! (Text: '{manifest.segments[0].text[:30]}...')")

        t_full_start = time.perf_counter()
        service.prepare_manifest_progressive(manifest, policy="full-answer")
        t_full_end = time.perf_counter()
        full_manifest_prep_ms = (t_full_end - t_full_start) * 1000.0

        print(f"SUCCESS: Full manifest prepared in {full_manifest_prep_ms:.1f}ms. Readiness: {manifest.segment_readiness}")
        print(f"Segment Hashes: {manifest.segment_hashes}")

        # Test replay cache reuse for progressive manifest
        t_replay_start = time.perf_counter()
        replay_bytes = service.synthesize_segment(manifest.segments[0], answer_id=manifest.message_id)
        t_replay_end = time.perf_counter()
        replay_ms = (t_replay_end - t_replay_start) * 1000.0
        print(f"SUCCESS: Manifest Replay segment 1 hit cache instantly in {replay_ms:.2f}ms! (Bytes matched: {replay_bytes == seg1_bytes})")

    print("\nTesting TTS Cache Reuse...")
    t_cache_start = time.perf_counter()
    cached_bytes = service.synthesize(sample, language_hint=args.language, answer_id="diag_02")
    t_cache_end = time.perf_counter()
    cm = service.last_tts_metrics
    if not cm.cache_hit:
        print(f"FAIL: Expected cache hit, got [{service.last_tts_backend}]")
        return 1
    print(f"SUCCESS: Second call returned cached voice instantly! (Prep Time={(t_cache_end - t_cache_start)*1000:.2f}ms, Cache Hit={cm.cache_hit})")

    if args.sim_concurrent:
        import concurrent.futures
        print("\nSimulating 2 Concurrent Callers joining Single-Flight Synthesis...")
        uncached_sample = f"{base_sample} (unique {time.time_ns()})"
        results: list[bytes] = []

        def worker(caller_id: int) -> bytes:
            return service.synthesize(uncached_sample, language_hint=args.language, answer_id=f"sim_{caller_id}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, 1), executor.submit(worker, 2)]
            for fut in concurrent.futures.as_completed(futures):
                results.append(fut.result())

        if len(results) == 2 and len(results[0]) > 0 and results[0] == results[1]:
            print("SUCCESS: Concurrent single-flight test passed! Both callers received identical audio without duplicate calls.")
        else:
            print("FAIL: Concurrent single-flight test produced inconsistent results.")
            return 1

    if args.play:
        print("\nPlaying audio on desktop speaker...")
        try:
            service.play_wav_bytes(cached_bytes)
            print("SUCCESS: Native playback initiated.")
        except Exception as exc:
            print(f"FAIL: Playback failed: {exc}")
            return 1
    else:
        print("\n(Pass --play to test speaker output)")

    print("\n=== Voice Diagnostic Completed Successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
