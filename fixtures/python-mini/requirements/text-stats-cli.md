# Text statistics command

Add a command-line tool so people can get statistics for a text file without
writing Python.

- `python -m textkit stats <file>` prints the number of lines, words and
  characters in the file, one per line: `lines: 3`, `words: 12`, `chars: 61`.
- `--json` prints the same numbers as one JSON object:
  `{"lines": 3, "words": 12, "chars": 61}`.
- `-` as the file name reads standard input.
- A missing file prints `error: <path> not found` to stderr and exits with code 2.
- The counting lives in a library function, `textkit.stats(text) -> dict`, so
  Python callers get the same numbers. Words are whitespace-separated.
