from pathlib import Path

mod_file = Path(SPECPATH, 'build.mod')
exec(mod_file.read_text())

version_info_file = './_DEPLOY/version_info.json'
additional_files = [(version_info_file, '.')] if Path(version_info_file).is_file() else []

calc_manager = create_exe(
        exe_name='calc_manager',
        scripts=['main.py'],
        collect_files=additional_files,
        )

collect('calc_manager', calc_manager)
