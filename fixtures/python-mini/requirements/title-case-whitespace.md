# Bug: title_case collapses whitespace

`title_case("hello   world")` returns `"Hello World"`. Runs of spaces are
collapsed to one, and leading or trailing whitespace, tabs and newlines are
lost.

Expected: only the letters change case. Every whitespace character stays
exactly where it was:

- `title_case("hello   world")` → `"Hello   World"`
- `title_case("  hello\tworld\n")` → `"  Hello\tWorld\n"`
- Existing behaviour stays: `title_case("hELLO wORLD")` → `"Hello World"`.
