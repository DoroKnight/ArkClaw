[app]
title = SJTUClaw
project_dir = ..
input_file = packaging/pet_entry.py
exec_directory = dist
project_file =
icon =

[python]
python_path =
packages = Nuitka==4.0

[qt]
qml_files =
excluded_qml_plugins =
modules = Core,Gui,Widgets,Network
plugins = platforms,styles

[nuitka]
mode = standalone
extra_args = --quiet --windows-console-mode=disable --msvc=14.4 --disable-cache=ccache --output-filename=SJTUClaw.exe --report=build/windows-standalone/compilation-report.xml --report-diffable --include-module=PySide6.QtCore --include-module=PySide6.QtGui --include-module=PySide6.QtWidgets --include-module=PySide6.QtNetwork --nofollow-import-to=tests --nofollow-import-to=scripts --nofollow-import-to=pydantic.mypy --nofollow-import-to=mypy --nofollow-import-to=mypy_extensions --nofollow-import-to=mypyc --nofollow-import-to=httpx._main --nofollow-import-to=pygments --noinclude-qt-translations
