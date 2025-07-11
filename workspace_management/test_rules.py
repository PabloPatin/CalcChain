LOADER_RULES = {
    'DATA_RULES': [
        ['01_1.?/.*', '<source:desc>/<>'],
        ['const/.*', '<source:desc>/tools/<path:name>'],
        ['.*[.]inp', 'inputs/<source:desc>/<path:name>'],
        ['.*[.]toml', '<path:name>'],
        ['.*', '<source:desc>/<path:name>'],
        ],
    }

RECORDER_RULES = {
    'RESULT_RULES': [
        ['.*result.txt', '<path:name>'],
        [r'.*(?P<info>\w)/.*[.]info', 'info<capt:info>/<path:name>'],
        ['data1/.*', '<path:parent>/<path:stem>.lock'],
        ],
    }
