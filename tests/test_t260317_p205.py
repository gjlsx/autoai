import pytest
from projectsa.quick_sort import quick_sort

def test_quick_sort_specific_array():
    input_arr = [45, 35, 74, 25, 81, 68, 98, 92, 48, 4]
    expected = [4, 25, 35, 45, 48, 68, 74, 81, 92, 98]
    assert quick_sort(input_arr) == expected

def test_quick_sort_empty():
    assert quick_sort([]) == []

def test_quick_sort_single():
    assert quick_sort([1]) == [1]
