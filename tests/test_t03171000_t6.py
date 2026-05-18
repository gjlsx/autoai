import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t6

def test_sort165_t6():
    assert sort165_t6() == 10
    print("Test sort165_t6 passed!")

if __name__ == "__main__":
    test_sort165_t6()
