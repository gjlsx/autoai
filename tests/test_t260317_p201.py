import pytest
from projectsa.bubble_sort import bubble_sort

def test_bubble_sort_specific_array():
    input_arr = [45, 35, 74, 25, 81, 68, 98, 92, 48, 4]
    expected = [4, 25, 35, 45, 48, 68, 74, 81, 92, 98]
    assert bubble_sort(input_arr) == expected

def test_bubble_sort_empty():
    assert bubble_sort([]) == []

def test_bubble_sort_single():
    assert bubble_sort([1]) == [1]
