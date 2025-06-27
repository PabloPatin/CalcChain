EXEC_RULES = {
    'bin/libs/*.dat': '<parent>/tot/<name>',
    'bin/*': '<name>',
    '*.exe*': 'bin/<name>',
    '*': '<name>',
    }

DATA_RULES = {
    '01_1?/*': '<root_dir>/<path>',
    'const/*': '<root_dir>/tools/<name>',
    '*.inp': 'inputs/<name>',
    '*': '<root_dir>/<name>',
    }
