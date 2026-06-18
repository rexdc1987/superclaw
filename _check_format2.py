# Examine the format string character by character
import re

fmt = 'mysql+pymysql://{}:***@{}:{}/{}?charset=utf8mb4'
print("Format string:", repr(fmt))
placeholders = [(m.start(), m.group()) for m in re.finditer(r'\{[^}]*\}', fmt)]
print("Placeholders:", placeholders)
print("Count:", len(placeholders))
print()
# Manual format test
result = fmt.format("u", "p", "h", 3306, "db")
print("5 args test:", result)
result4 = fmt.format("u", "p", "h", 3306)
print("4 args test:", result4)
