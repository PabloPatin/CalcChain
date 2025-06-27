from itertools import chain

def create_exe(
        exe_name: str,
        scripts: list[str],
        *,
        hidden_imports: list[str] | None = None,
        collect_files: list[tuple[str, str]] | None = None,
        windowed: bool = False,
        icon_file: str | None = None,
        use_pyinstaller_icon: bool = False,
        contents_directory: str = 'app',
        ) -> tuple:
    a = Analysis(scripts, datas=collect_files, hiddenimports=hidden_imports)
    pyz = PYZ(a.pure)
    exe = EXE(pyz, a.scripts, [],
              name=exe_name,
              console=not windowed,
              contents_directory=contents_directory,
              icon=icon_file if icon_file or use_pyinstaller_icon else 'NONE',
              exclude_binaries=True,
              upx=True)
    return exe, a.binaries, a.datas

def collect(dist_name: str, *exe_items: tuple) -> None:
    items_to_collect = chain.from_iterable(exe_items)
    _ = COLLECT(*items_to_collect, name=dist_name, upx=True)
