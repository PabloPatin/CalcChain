from pathlib import Path

mod_file = Path(SPECPATH, 'build.mod')
exec(mod_file.read_text())

version_info_file = './_DEPLOY/version_info.json'
additional_files = [(version_info_file, '.')] if Path(version_info_file).is_file() else []

calcchain_backend = create_exe(
        exe_name='calcchain_backend',
        scripts=['apps/backend/src/calcchain_backend/cli.py'],
        collect_files=additional_files,
        )

collect('calcchain_backend', calcchain_backend)
