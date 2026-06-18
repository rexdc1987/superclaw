from src.models.database import _build_url
result = _build_url({'database':{'engine':'mysql','host':'127.0.0.1','port':3306,'name':'superclaw','user':'superclaw','password':'test123'}})
print("MySQL URL:", result)
print()
# The format string is: "mysql+pymysql://{}:***@{}:{}/{}?charset=utf8mb4".format(user, pwd, host, port, name)
# This has 3 {} placeholders but 5 arguments. 
# user -> first {}, pwd -> second {}, host -> third {}
# port and name are EXTRA args (ignored by .format())
# The '***' is LITERAL in the string, not the password
print("BUG: password='test123' should appear in URL but '***' is hardcoded")
print("BUG: 'port' (3306) is 4th arg, fills no placeholder")
print("BUG: 'name' (superclaw) is 5th arg, fills no placeholder")
print("BUG: host='127.0.0.1' fills 2nd {} but that's the port position")
print()
print("Expected: mysql+pymysql://superclaw:test123@127.0.0.1:3306/superclaw?charset=utf8mb4")
print("Actual:  ", result)
