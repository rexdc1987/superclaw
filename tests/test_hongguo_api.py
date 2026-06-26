"""Test Hongguo API import"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from api.main import app
from api.hongguo.router import router

print('FastAPI app created OK')
print(f'App routes: {len(app.routes)}')
print(f'Hongguo routes: {len(router.routes)}')

for r in router.routes:
    methods = getattr(r, 'methods', set())
    path = getattr(r, 'path', '?')
    print(f'  {methods} {path}')

print('\nAll API tests passed!')
