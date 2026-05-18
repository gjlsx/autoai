import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t2

def test_sort165_t2():
    assert sort165_t2() == 20
    print("Test sort165_t2 passed!")

if __name__ == "__main__":
    test_sort165_t2()
