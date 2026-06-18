import sys
sys.path.insert(0, ".")
from src.models.database import _build_url
import inspect

# Get the source code of _build_url
src = inspect.getsource(_build_url)
print("Source code:")
print(src)
print()

# Now test
result = _build_url({'database':{'engine':'mysql','host':'h','port':3306,'name':'db','user':'u','password':'p'}})
print("Test result:", result)
print()

# Also test with empty password
result2 = _build_url({'database':{'engine':'mysql','host':'h','port':3306,'name':'db','user':'u','password':''}})
print("Empty pw result:", result2)
