LOADER_RULES = {
    'DATA_RULES': [
        ['01_1.?/.*', '<source:desc>/<>'],
        ['const/.*', '<source:desc>/tools/<path:name>'],
        ['.*[.]inp', 'inputs/<source:desc>/<path:name>'],
        ['.*', '<source:desc>/<path:name>'],
        ],
    }

RECORDER_RULES = {
    'RESULT_RULES': [
        ['*/result.txt', '<>'],
        ],
    }
