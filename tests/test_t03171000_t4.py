import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t4

def test_sort165_t4():
    assert sort165_t4() == 40
    print("Test sort165_t4 passed!")

if __name__ == "__main__":
    test_sort165_t4()
