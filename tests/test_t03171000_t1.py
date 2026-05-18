import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t1

def test_sort165_t1():
    assert sort165_t1() == 10
    print("Test sort165_t1 passed!")

if __name__ == "__main__":
    test_sort165_t1()
