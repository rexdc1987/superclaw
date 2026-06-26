import sys, os
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
from models.database import init_db
from api.main import app
if __name__ == '__main__':
    init_db()
    print('DB OK, starting on :8002')
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8002)
