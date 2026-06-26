"""Run SuperClaw API server"""
import sys, os
sys.path = [p for p in sys.path if 'hermes' not in p.lower()]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
import uvicorn
if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8890, reload=False)
