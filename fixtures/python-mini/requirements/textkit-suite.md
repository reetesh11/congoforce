# textkit 1.0

Turn textkit into a complete text toolkit for our content team.

1. `slugify(text)`: URL slugs with Unicode transliteration (é → e, ß → ss).
2. `truncate(text, width, ellipsis="…")` that never cuts a word in half.
3. `wrap(text, width)`: word wrapping that keeps paragraphs and indentation.
4. `sentences(text)`: sentence splitting that knows common abbreviations
   (Dr., e.g., U.S.).
5. `readability(text)`: Flesch reading ease and Flesch-Kincaid grade.
6. A `textkit` command with subcommands for every function above, reading
   files or stdin, with `--json` output.
7. A plug-in system so teams can register their own transforms via entry points.
8. A config file (`textkit.toml`) for default widths, ellipsis and locale.
9. Localised abbreviation lists for English, German and French.
10. Full documentation with examples for every function and subcommand.
