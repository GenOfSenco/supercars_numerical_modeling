from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "PROJECT_EXPORT.md"
INCLUDE_ROOTS = ["aerogen", "web", "aerogen.py", "run.bat", "README.md", "requirements.txt"]
SKIP_NAMES = {"__pycache__", ".git", "cfd_runs", "PROJECT_EXPORT.md", "export_to_md.py"}


def collect_files():
    found = []
    for item in INCLUDE_ROOTS:
        p = ROOT / item
        if p.is_file():
            found.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if not f.is_file():
                    continue
                if any(part in SKIP_NAMES for part in f.parts):
                    continue
                found.append(f)
    return sorted(set(found), key=lambda x: x.as_posix())


def lang(path: Path) -> str:
    return {
        ".py": "python",
        ".js": "javascript",
        ".css": "css",
        ".html": "html",
        ".bat": "bat",
        ".md": "markdown",
    }.get(path.suffix.lower(), "")


def build_tree(files):
    lines = ["Supercars/"]
    nodes = {}
    for f in files:
        rel = f.relative_to(ROOT)
        parts = rel.parts
        for i in range(len(parts)):
            key = "/".join(parts[: i + 1])
            nodes[key] = parts[: i + 1]

    def children_of(prefix_parts):
        prefix = "/".join(prefix_parts)
        kids = set()
        for key in nodes:
            p = key.split("/")
            if len(p) == len(prefix_parts) + 1 and p[: len(prefix_parts)] == prefix_parts:
                kids.add(p[-1])
        return sorted(kids)

    def walk(prefix_parts, indent):
        kids = children_of(prefix_parts)
        for i, name in enumerate(kids):
            last = i == len(kids) - 1
            branch = "└── " if last else "├── "
            lines.append(indent + branch + name)
            child_parts = prefix_parts + [name]
            child_key = "/".join(child_parts)
            if child_key in nodes and (ROOT / Path(*child_parts)).is_dir():
                walk(child_parts, indent + ("    " if last else "│   "))

    walk([], "")
    return lines


def main():
    files = collect_files()
    parts = [
        "# Aerogen — экспорт исходников",
        "",
        "Полный дамп кода для ревью и архива. Актуальная документация — в [README.md](README.md).",
        "",
        "| | |",
        "|---|---|",
        "| Python | 3.10+ |",
        "| Зависимости | `pip install -r requirements.txt` |",
        "| Запуск | `python aerogen.py` |",
        "| 3D UI | Three.js (CDN в `web/index.html`) |",
        "",
        "## Дерево файлов",
        "",
        "```text",
        *build_tree(files),
        "```",
        "",
        f"**Файлов в экспорте:** {len(files)}",
        "",
        "---",
        "",
    ]

    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        text = f.read_text(encoding="utf-8").rstrip("\n")
        parts.append(f"## `{rel}`")
        parts.append("")
        parts.append(f"```{lang(f)}")
        parts.append(text)
        parts.append("```")
        parts.append("")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"OK: {OUT} ({OUT.stat().st_size:,} bytes, {len(files)} files)")


if __name__ == "__main__":
    main()
