#!/usr/bin/env python3
"""Batch CLI for running LLM Council on multiple questions.

Imports run_full_council() directly — no HTTP server needed.

Usage:
    python -u batch_cli.py --questions path/to/questions.json --output-dir path/to/examples/
    python -u batch_cli.py --questions questions.json --output-dir examples/ --start-from 5
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

# Force unbuffered output
import functools
print = functools.partial(print, flush=True)

# Fix imports: add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.council import run_full_council


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text[:80].rstrip('-')


def format_walkthrough(question: str, category: str, topic: str,
                       stage1_results: list, stage2_results: list,
                       stage3_result: dict, metadata: dict) -> str:
    """Format council results into walkthrough markdown."""
    lines = []

    lines.append(f"# {topic}\n")
    lines.append(f"**Category:** {category}\n")
    lines.append(f"**Question:** {question}\n")
    lines.append("---\n")

    # Stage 3 synthesis as main walkthrough
    synthesis = stage3_result.get('response', '')
    lines.append(synthesis)
    lines.append("\n---\n")

    # Individual model responses in collapsible sections
    if stage1_results:
        lines.append("## Individual Model Responses\n")
        for result in stage1_results:
            model = result.get('model', 'Unknown')
            response = result.get('response', '')
            model_short = model.split('/')[-1]
            lines.append(f"<details>\n<summary>{model_short}</summary>\n")
            lines.append(f"{response}\n")
            lines.append("</details>\n")

    # Aggregate scores
    if metadata.get('aggregate_scores'):
        lines.append("\n## Council Scores\n")
        axes = metadata.get('axes', [])
        axis_names = [a['name'] for a in axes]

        lines.append(f"| Model | {' | '.join(axis_names)} | Overall |")
        lines.append(f"|{'|'.join(['---'] * (len(axis_names) + 2))}|")
        for agg in metadata['aggregate_scores']:
            model_short = agg['model'].split('/')[-1]
            scores = [str(agg['axis_scores'].get(name, 'N/A')) for name in axis_names]
            lines.append(f"| {model_short} | {' | '.join(scores)} | {agg['overall_score']} |")
        lines.append("")

    return '\n'.join(lines)


async def process_question(idx: int, total: int, item: dict,
                           template: str | None, output_dir: Path,
                           max_retries: int = 3) -> bool:
    """Process a single question through the council with retry logic."""
    question = item['question']
    category = item.get('category', 'Uncategorized')
    topic = item.get('topic', 'Unknown Topic')
    slug = slugify(topic)
    output_file = output_dir / f"{slug}.md"

    # Skip if already exists
    if output_file.exists():
        print(f"  [{idx+1}/{total}] SKIP (exists): {slug}")
        return True

    # Apply template if provided
    query = question
    if template:
        query = template.replace('{{question}}', question)

    for attempt in range(max_retries):
        try:
            start = time.time()
            print(f"  [{idx+1}/{total}] Processing: {topic}...")

            stage1, stage2, stage3, metadata = await run_full_council(query)

            elapsed = time.time() - start

            if stage3.get('model') == 'error':
                print(f"  [{idx+1}/{total}] ERROR: All models failed for {topic}")
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1) * 5
                    print(f"    Retrying in {wait}s (attempt {attempt+2}/{max_retries})...")
                    await asyncio.sleep(wait)
                    continue
                return False

            # Format and save
            walkthrough = format_walkthrough(
                question, category, topic,
                stage1, stage2, stage3, metadata
            )
            output_file.write_text(walkthrough)
            print(f"  [{idx+1}/{total}] DONE ({elapsed:.1f}s): {slug}.md")
            return True

        except Exception as e:
            error_msg = str(e)
            print(f"  [{idx+1}/{total}] ERROR (attempt {attempt+1}): {error_msg}")

            # Retry with backoff for rate limits
            if '429' in error_msg or 'rate' in error_msg.lower():
                wait = 2 ** (attempt + 1) * 10  # 20s, 40s, 80s
                print(f"    Rate limited. Waiting {wait}s...")
                await asyncio.sleep(wait)
            elif attempt < max_retries - 1:
                wait = 2 ** (attempt + 1) * 5
                print(f"    Retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                return False

    return False


async def run_batch(questions_file: Path, output_dir: Path,
                    template_file: Path | None = None,
                    start_from: int = 0,
                    delay: float = 2.0) -> None:
    """Run the full batch process."""
    # Load questions
    with open(questions_file) as f:
        questions = json.load(f)

    # Load template
    template = None
    if template_file:
        template = template_file.read_text()

    # Create output dir
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(questions)
    subset = questions[start_from:]

    print(f"\n{'='*60}")
    print(f"LLM Council Batch Processing")
    print(f"{'='*60}")
    print(f"Questions: {total} total, starting from #{start_from+1}")
    print(f"Output: {output_dir}")
    print(f"Template: {template_file or 'None (raw questions)'}")
    print(f"{'='*60}\n")

    succeeded = 0
    failed = 0
    skipped = 0
    start_time = time.time()

    for i, item in enumerate(subset):
        global_idx = start_from + i

        result = await process_question(global_idx, total, item, template, output_dir)
        if result:
            # Check if it was skipped or newly processed
            slug = slugify(item.get('topic', 'unknown'))
            output_file = output_dir / f"{slug}.md"
            if output_file.exists():
                succeeded += 1
            else:
                skipped += 1
        else:
            failed += 1

        # Progress summary every 5 questions
        if (i + 1) % 5 == 0:
            elapsed = time.time() - start_time
            avg_per_q = elapsed / (i + 1)
            remaining = avg_per_q * (len(subset) - i - 1)
            print(f"\n  --- Progress: {i+1}/{len(subset)} | "
                  f"OK={succeeded} FAIL={failed} | "
                  f"~{remaining/60:.0f}m remaining ---\n")

        # Small delay between questions to avoid rate limits
        if i < len(subset) - 1:
            await asyncio.sleep(delay)

    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"COMPLETE in {elapsed/60:.1f} minutes")
    print(f"Succeeded: {succeeded}")
    print(f"Failed: {failed}")
    print(f"Total files in output: {len(list(output_dir.glob('*.md')))}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description='Batch LLM Council processing')
    parser.add_argument('--questions', '-q', type=Path, required=True,
                        help='JSON file with questions')
    parser.add_argument('--output-dir', '-o', type=Path, required=True,
                        help='Directory to write walkthrough markdown files')
    parser.add_argument('--template', '-t', type=Path, default=None,
                        help='Template file with {{question}} placeholder')
    parser.add_argument('--start-from', '-s', type=int, default=0,
                        help='Skip first N questions (0-indexed)')
    parser.add_argument('--delay', '-d', type=float, default=2.0,
                        help='Delay in seconds between questions (default: 2)')

    args = parser.parse_args()

    if not args.questions.exists():
        print(f"Error: Questions file not found: {args.questions}")
        sys.exit(1)

    if args.template and not args.template.exists():
        print(f"Error: Template file not found: {args.template}")
        sys.exit(1)

    asyncio.run(run_batch(
        questions_file=args.questions,
        output_dir=args.output_dir,
        template_file=args.template,
        start_from=args.start_from,
        delay=args.delay,
    ))


if __name__ == '__main__':
    main()
