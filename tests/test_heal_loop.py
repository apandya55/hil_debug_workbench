from pathlib import Path

from hil_cli.heal_loop import _apply_fix


def test_apply_fix_rejects_paths_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "firmware"
    project.mkdir()
    external = tmp_path / "secret.txt"
    external.write_text("safe", encoding="utf-8")

    modified = _apply_fix(
        {"fixes": [{"file": str(external), "old_code": "safe", "new_code": "changed"}]},
        str(project),
    )

    assert modified == []
    assert external.read_text(encoding="utf-8") == "safe"


def test_apply_fix_rejects_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "firmware"
    project.mkdir()
    external = tmp_path / "external.cpp"
    external.write_text("old", encoding="utf-8")
    (project / "link.cpp").symlink_to(external)

    modified = _apply_fix(
        {"fixes": [{"file": "link.cpp", "old_code": "old", "new_code": "new"}]},
        str(project),
    )

    assert modified == []
    assert external.read_text(encoding="utf-8") == "old"


def test_apply_fix_updates_file_inside_project(tmp_path: Path) -> None:
    project = tmp_path / "firmware"
    project.mkdir()
    source = project / "main.cpp"
    source.write_text("int value = 1;", encoding="utf-8")

    modified = _apply_fix(
        {"fixes": [{"file": "main.cpp", "old_code": "value = 1", "new_code": "value = 2"}]},
        str(project),
    )

    assert modified == [str(source)]
    assert source.read_text(encoding="utf-8") == "int value = 2;"
