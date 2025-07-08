RULES = {
    'DATA_RULES': [
        ['01_1.?/.*', '<source:desc>/<>'],
        ['const/.*', '<source:desc>/tools/<path:name>'],
        ['.*[.]inp', 'inputs/<source:desc>/<path:name>'],
        ['.*', '<source:desc>/<path:name>'],
        ],
    'EXEC_RULES': [
        ['bin/libs/.*[.]dat', '<path:parent>/tot/<path:name>'],
        ['bin/.*', '<path:name>'],
        ['.+[.]exe.*', 'bin/<path:name>'],
        ['.*', '<path:name>'],
        ],
    }
