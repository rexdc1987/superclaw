import sys
sys.path.insert(0, ".")
from src.models.database import _build_url
result = _build_url({'database':{'engine':'mysql','host':'127.0.0.1','port':3306,'name':'superclaw','user':'superclaw','password':'test123'}})
print("MySQL URL:", result)
if "***" in result:
    print("BUG: Password replaced with '***' in URL")
if "test123" in result:
    print("Password correctly included")
