#!/usr/bin/env python3
"""
Benchmark utility for GyanVerse Academy tutor response latency.
Validates instant local greeting routing (< 500ms max, < 100ms median) and online timing breakdown.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from statistics import median

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase11_core import StudentLearningContext
from phase11_ai import GyanVerseAIService


def main() -> int:
    parser = argparse.ArgumentParser(description="GyanVerse Tutor Latency Benchmark")
    parser.add_argument("--online", action="store_true", help="Run 1 online provider request if configured")
    parser.add_argument("--online-stream", action="store_true", help="Run 1 online streaming provider request if configured")
    parser.add_argument("--iterations", type=int, default=20, help="Number of local benchmark iterations (default: 20)")
    args = parser.parse_args()

    print("=== GyanVerse Tutor Latency Benchmark ===")
    service = GyanVerseAIService()
    context = StudentLearningContext(name="BenchmarkStudent", standard=7, board="GSEB", preferred_language="English")

    greetings = ["hello", "hi", "good morning", "namaste", "thanks", "bye"]
    latencies_ms: list[float] = []

    print(f"Benchmarking instant local routing ({args.iterations} iterations across greetings)...")
    for i in range(args.iterations):
        msg = greetings[i % len(greetings)]
        t_start = time.perf_counter()
        answer = service.ask(message=msg, context=context)
        t_end = time.perf_counter()
        elapsed_ms = (t_end - t_start) * 1000.0
        latencies_ms.append(elapsed_ms)
        if service.last_metrics.route != "instant-local":
            print(f"FAIL: Greeting '{msg}' was routed as '{service.last_metrics.route}' instead of 'instant-local'")
            return 1

    med = median(latencies_ms)
    sorted_lat = sorted(latencies_ms)
    p95_idx = int(len(sorted_lat) * 0.95)
    p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
    max_lat = max(latencies_ms)

    print(f"\nLocal Greeting Latency Results ({len(latencies_ms)} runs):")
    print(f"  Median: {med:.2f} ms (Target: < 100 ms)")
    print(f"  p95:    {p95:.2f} ms")
    print(f"  Max:    {max_lat:.2f} ms (Limit: < 500 ms)")

    if max_lat > 500.0:
        print(f"FAIL: Maximum latency {max_lat:.2f} ms exceeded the 500 ms limit!")
        return 1

    print("SUCCESS: Instant local routing benchmark passed!")

    if args.online:
        print("\n--- Running Online Provider Latency Sample ---")
        if not service.configured:
            print("SKIPPED: Online AI is not configured or in retry cooldown.")
        else:
            t_start = time.perf_counter()
            answer = service.ask(message="Explain what is a fraction in simple terms.", context=context)
            m = service.last_metrics
            print(f"Route: {m.route}")
            print(f"Backend: {m.backend}")
            print(f"Prompt Build:       {m.prompt_build_ms:.2f} ms")
            print(f"Attachment Prepare: {m.attachment_prepare_ms:.2f} ms")
            print(f"Provider API:       {m.provider_ms:.2f} ms")
            print(f"Formatting:         {m.formatting_ms:.2f} ms")
            print(f"Total Response:     {m.total_ms:.2f} ms")

    if args.online_stream:
        print("\n--- Running Online Streaming Provider Latency Sample ---")
        if not service.configured:
            print("SKIPPED: Online AI is not configured or in retry cooldown.")
        else:
            first_chunk_text = [""]
            def chunk_cb(accumulated: str, chunk: str) -> None:
                if not first_chunk_text[0] and chunk:
                    first_chunk_text[0] = chunk

            answer = service.ask_stream(
                message="What is photosynthesis? Explain in simple terms for Class 7.",
                context=context,
                on_chunk=chunk_cb,
            )
            m = service.last_metrics
            print(f"Model:                {service.model_name}")
            print(f"Backend:              {m.backend}")
            print(f"Route:                {m.route}")
            print(f"First Chunk (TTFT):   {m.provider_first_chunk_ms:.2f} ms")
            print(f"Provider Complete:    {m.provider_complete_ms:.2f} ms")
            print(f"Total Response:       {m.total_ms:.2f} ms")
            print(f"Chunk Count:          {m.chunk_count}")
            print(f"First Chunk Sample:   {first_chunk_text[0][:40]!r}")

    print("\n=== Benchmark Completed Successfully ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
