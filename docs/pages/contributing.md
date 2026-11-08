# Contributing

Contributions are welcome: bug reports, ideas to make indexing faster, support for other variants of the template.

## Reporting issues

Open an issue on [GitHub](https://github.com/academic-templates/course-index/issues) and include:

- the Course Index version (`course-index --version`);
- what you did and what happened (a screenshot helps for display issues);
- if possible, the `.idx` file or the lines causing the issue.

## Security

Please do **not** report vulnerabilities in public issues. See the
[security policy](https://github.com/academic-templates/course-index/blob/main/SECURITY.md): report them privately
through the repository's *Security* tab (*Report a vulnerability*).

Dependencies are monitored by Dependabot and audited with [pip-audit](https://github.com/pypa/pip-audit) by the
`security` workflow (`.github/workflows/security.yml`), on every push and pull request to `main` and weekly.

## Development setup

```console
$ git clone https://github.com/academic-templates/course-index
$ cd course-index
$ pip install -e .
$ pip install pytest pytest-cov flake8
$ pytest --cov=course_index
$ flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

The compilation tests are skipped when `makeindex` and `pdflatex` are not installed. The TUI tests drive the
application with Textual's pilot, without a terminal, and the GUI tests drive the window with Qt's offscreen platform
(`QT_QPA_PLATFORM=offscreen`), without a display.

CI (`.github/workflows/python-package.yml`) runs the tests on Python 3.10 to 3.13 (with TeX Live on the Python 3.13
run, which also publishes the coverage badge).

## Releasing

The version is stored in `src/course_index/VERSION.txt`. On every push to `main`, CI checks whether that version is
already on PyPI. If not, it builds the package and publishes it.

## Building this documentation

```console
$ pip install -r docs/requirements.txt
$ mkdocs serve -f docs/mkdocs.yml          # live preview at http://127.0.0.1:8000
$ mkdocs build --strict -f docs/mkdocs.yml # what Read the Docs runs
```

Read the Docs builds the site from `.readthedocs.yaml` at the root of the repository.
