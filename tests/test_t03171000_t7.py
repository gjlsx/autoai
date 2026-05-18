import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t7

def test_sort165_t7():
    assert sort165_t7() == 5
    print("Test sort165_t7 passed!")

if __name__ == "__main__":
    test_sort165_t7()
