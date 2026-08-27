#!/usr/bin/env python
r"""Ask Document Memory what it observed.

The query interface, deliberately independent of any voice path. A future
Siri shortcut, a custom wake word or an iOS screen would all sit ABOVE
this; none of them is required for the feature to work, and building the
voice layer first would have made the memory untestable.

Three questions, matching what a wearer actually asks:

    --recent 5                     what have I looked at lately
    --minutes-ago 30 --window 15   the one from about half an hour ago
    --text "transformer attention" the one about transformers

The content search is LEXICAL. It matches a document containing the word;
it will not match a paraphrase that never uses it. Every result says so.

    .venv\Scripts\python.exe scripts/document_query.py --recent 5
    .venv\Scripts\python.exe scripts/document_query.py --text "return policy"
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tower.artifact_paths import artifact_root_arg  # noqa: E402
from tower.document_memory.retrieval import DocumentMemory  # noqa: E402
from tower.document_memory.store import DocumentStore  # noqa: E402

DEFAULT_ROOT = Path("data/document_memory")


def _document_line(document, when: float) -> str:
    age_minutes = (when - document.observed_at) / 60.0
    title = document.title or "(no title recognised)"
    return (
        f"  {document.document_id[:8]}  {age_minutes:7.1f} min ago  "
        f"{document.pages_observed}p  {document.confidence.value:<7} {title[:60]}"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Query observed documents (read-only unless --purge)."
    )
    parser.add_argument(
        "--root", type=artifact_root_arg, default=str(DEFAULT_ROOT)
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--recent", type=int, default=None, metavar="N")
    parser.add_argument("--text", default=None, help="Lexical search over OCR text.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--minutes-ago",
        type=float,
        default=None,
        help='"about N minutes ago" -- the centre of a time window.',
    )
    parser.add_argument(
        "--window",
        type=float,
        default=15.0,
        metavar="MINUTES",
        help="How wide 'about' is. Default 15 minutes either side.",
    )
    parser.add_argument("--coverage", default=None, metavar="DOCUMENT_ID")
    parser.add_argument("--purge", default=None, metavar="DOCUMENT_ID")
    parser.add_argument(
        "--purge-all",
        action="store_true",
        help="Really delete every stored document. Reports what it could not.",
    )
    parser.add_argument("--now", type=float, default=None, help="Override the clock.")
    args = parser.parse_args(argv)

    asked = [
        args.recent is not None,
        args.text is not None,
        args.minutes_ago is not None,
        args.coverage is not None,
        args.purge is not None,
        args.purge_all,
    ]
    if sum(1 for flag in asked if flag) != 1:
        parser.error(
            "exactly one of --recent, --text, --minutes-ago, --coverage, "
            "--purge or --purge-all is required"
        )

    store = DocumentStore(args.root)
    memory = DocumentMemory(store)
    now = time.time() if args.now is None else args.now

    if args.purge_all or args.purge:
        report = store.purge(None if args.purge_all else args.purge)
        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            print(f"documents removed  {report['documents_removed']}")
            print(f"images removed     {report['images_removed']}")
            print(f"images retained    {len(report['images_retained'])}")
            print(f"complete           {report['complete']}")
            if not report["complete"]:
                # A purge that could not delete everything must never be
                # presented as success (06-PRIVACY-DATA).
                print("\nWARNING: deletion INCOMPLETE. These remain on disk:")
                for path in report["images_retained"]:
                    print(f"  {path}")
        return 0 if report["complete"] else 1

    if args.coverage is not None:
        coverage = memory.coverage(args.coverage)
        if coverage is None:
            print(f"no document {args.coverage!r}", file=sys.stderr)
            return 2
        if args.format == "json":
            print(json.dumps(coverage, indent=2))
        else:
            for key, value in coverage.items():
                print(f"{key:22s} {value}")
        return 0

    if args.text is not None:
        result = memory.search_text(args.text, limit=args.limit)
        if args.format == "json":
            print(json.dumps(result.to_json_dict(), indent=2))
            return 0 if result.sufficient_evidence else 1
        if not result.sufficient_evidence:
            print(f"No record: {result.reason}")
            print(f"(searched {result.searched_documents} observed documents)")
            return 1
        print(f"=== lexical matches for {args.text!r} ===")
        for match in result.matches:
            print(
                f"  {match.document_id[:8]}  score {match.score:6.3f}  "
                f"terms {','.join(match.matched_terms)}"
            )
            print(f"      {match.document.title or '(no title)'}")
            print(f"      {match.snippet}")
        print(
            "\nLEXICAL match on captured text, not semantic. A paraphrase "
            "that shares no words will not be found."
        )
        return 0

    documents = (
        memory.recent(args.recent)
        if args.recent is not None
        else memory.around(
            now - args.minutes_ago * 60.0, window_seconds=args.window * 60.0
        )
    )

    if args.format == "json":
        print(
            json.dumps(
                {
                    "count": len(documents),
                    "documents": [
                        document.to_json_dict() for document in documents
                    ],
                },
                indent=2,
            )
        )
        return 0 if documents else 1

    if not documents:
        print("No record of observing a document in that window.")
        print("(that is a statement about what was captured, not about the world)")
        return 1
    print(f"{'id':10s}{'observed':>16s}  pages  conf     title")
    for document in documents:
        print(_document_line(document, now))
    print("\nOBSERVED, NOT READ. Times are tower-receipt, not capture time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
