import os
from pathlib import Path

ENV_FILE = Path(os.path.expanduser('~/.config/second-brain/mcp-server.env'))

def load_env():
    env_vars = dict(os.environ)
    if ENV_FILE.exists():
        try:
            with open(ENV_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        val = v.strip()
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        env_vars[k.strip()] = val
        except Exception:
            pass
    return env_vars
