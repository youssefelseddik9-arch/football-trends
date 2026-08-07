import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publisher import rebuild_all_existing

if __name__ == "__main__":
    rebuild_all_existing()
