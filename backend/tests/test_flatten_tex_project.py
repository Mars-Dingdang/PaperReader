from pathlib import Path

from app.services.latex_service import flatten_tex_project


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_flatten_inlines_input_files_recursively(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\\documentclass{article}\n\\begin{document}\n\\input{sections/intro}\n\\input{sections/method.tex}\n\\end{document}\n",
    )
    _write(tmp_path / "sections" / "intro.tex", "Intro prose.\n\\input{details}\n")
    _write(tmp_path / "sections" / "details.tex", "Nested detail.\n")
    _write(tmp_path / "sections" / "method.tex", "Method prose.\n")

    flattened = flatten_tex_project(main)

    assert "Intro prose." in flattened
    assert "Nested detail." in flattened
    assert "Method prose." in flattened
    assert "\\input" not in flattened


def test_flatten_inlines_include(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\\documentclass{article}\n\\begin{document}\n\\include{chapters/one}\n\\end{document}\n",
    )
    _write(tmp_path / "chapters" / "one.tex", "Chapter one.\n")

    assert "Chapter one." in flatten_tex_project(main)


def test_flatten_keeps_commented_input(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\\begin{document}\n% \\input{draft}\n100\\% \\input{real}\n\\end{document}\n",
    )
    _write(tmp_path / "real.tex", "Real content.\n")
    _write(tmp_path / "draft.tex", "Draft content.\n")

    flattened = flatten_tex_project(main)

    assert "% \\input{draft}" in flattened
    assert "Draft content." not in flattened
    assert "Real content." in flattened


def test_flatten_keeps_missing_file_command(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\\begin{document}\n\\input{does_not_exist}\n\\end{document}\n",
    )

    assert flatten_tex_project(main) == main.read_text(encoding="utf-8")


def test_flatten_stops_include_cycles(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\\begin{document}\n\\input{a}\n\\end{document}\n",
    )
    _write(tmp_path / "a.tex", "A text.\\input{b}\n")
    _write(tmp_path / "b.tex", "B text.\\input{a}\n")

    flattened = flatten_tex_project(main)

    assert flattened.count("A text.") == 1
    assert flattened.count("B text.") == 1


def test_flatten_single_file_returns_content(tmp_path: Path) -> None:
    main = _write(
        tmp_path / "main.tex",
        "\\documentclass{article}\n\\begin{document}\nHello world.\n\\end{document}\n",
    )

    assert flatten_tex_project(main) == main.read_text(encoding="utf-8")
