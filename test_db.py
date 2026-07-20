import os

import pymysql

try:
    c = pymysql.connect(
        host=os.environ.get("SUPERCLAW_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("SUPERCLAW_DB_PORT", "3308")),
        user=os.environ.get("SUPERCLAW_DB_USER", "superclaw"),
        password=os.environ.get("SUPERCLAW_DB_PASSWORD", ""),
        database=os.environ.get("SUPERCLAW_DB_NAME", "superclaw"),
    )
    print("OK")
    c.close()
except Exception as e:
    print("FAIL", e)
