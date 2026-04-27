#!/usr/bin/env python3
"""
Study Agent — CLI entry point.

Usage examples:

  # Dry-run: print TypeScript without writing
  python backend/agents/study_agent/run_agent.py \\
    --topic postura-anatomia-tecnica-basica \\
    --action exercises --count 2 --dry-run

  # Write 3 new exercises to studyExercises.ts
  python backend/agents/study_agent/run_agent.py \\
    --topic escalas-e-modos --action exercises --count 3

  # Generate theory exercises
  python backend/agents/study_agent/run_agent.py \\
    --topic arpejos --action theory --count 2

  # List all topic IDs currently in studyExercises.ts
  python backend/agents/study_agent/run_agent.py --list-topics
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running directly from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import content_generator
import ts_patcher


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Study Agent: generate exercises/theory for the Tabzer study page."
    )
    parser.add_argument("--topic", help="Topic ID (e.g. postura-anatomia-tecnica-basica)")
    parser.add_argument(
        "--action",
        choices=["exercises", "theory", "both"],
        default="exercises",
        help="What to generate (default: exercises)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=2,
        help="Number of exercises to generate (default: 2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated TypeScript without writing to disk",
    )
    parser.add_argument(
        "--list-topics",
        action="store_true",
        help="List all topic IDs present in studyExercises.ts and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also print generated exercises as JSON to stdout",
    )
    args = parser.parse_args()

    if args.list_topics:
        topics = ts_patcher.list_topics()
        print("Topics in studyExercises.ts:")
        for t in topics:
            count = ts_patcher.topic_exercise_count(t)
            print(f"  {t}  ({count} exercises)")
        return

    if not args.topic:
        parser.error("--topic is required unless --list-topics is used")

    topic_id: str = args.topic
    count: int = max(1, args.count)
    action: str = args.action

    print(f"[study_agent] Generating {count} {action} for topic: {topic_id}", file=sys.stderr)

    exercises = content_generator.generate(topic_id=topic_id, count=count, action=action)

    if not exercises:
        print("[study_agent] No exercises generated.", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(exercises, ensure_ascii=False, indent=2))

    preview = ts_patcher.preview(exercises)

    if args.dry_run:
        print("\n── DRY RUN — TypeScript preview ──")
        print(preview)
        print(f"\n[study_agent] Would append {len(exercises)} exercise(s) to topic '{topic_id}'")
        return

    ts_patcher.append_exercises(exercises, topic_id=topic_id)
    print(
        f"[study_agent] ✓ Appended {len(exercises)} exercise(s) to "
        f"studyExercises.ts → topic '{topic_id}'"
    )
    print(f"[study_agent] Current count: {ts_patcher.topic_exercise_count(topic_id)}")


if __name__ == "__main__":
    main()
