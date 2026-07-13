#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def extract_object(text: str):
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object start found")
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unterminated JSON object")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: extract_judge_json.py LAST_MESSAGE")
    text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    obj = extract_object(text)
    print(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
