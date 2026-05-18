import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t3

def test_sort165_t3():
    assert sort165_t3() == 30
    print("Test sort165_t3 passed!")

if __name__ == "__main__":
    test_sort165_t3()
