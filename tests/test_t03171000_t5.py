import sys
import os
sys.path.append(os.getcwd())

from cline_worker import sort165_t5

def test_sort165_t5():
    assert sort165_t5() == 50
    print("Test sort165_t5 passed!")

if __name__ == "__main__":
    test_sort165_t5()
