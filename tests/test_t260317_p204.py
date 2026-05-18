import pytest
from projectsa.merge_sort import merge_sort

def test_merge_sort_specific_array():
    input_arr = [45, 35, 74, 25, 81, 68, 98, 92, 48, 4]
    expected = [4, 25, 35, 45, 48, 68, 74, 81, 92, 98]
    assert merge_sort(input_arr) == expected

def test_merge_sort_empty():
    assert merge_sort([]) == []

def test_merge_sort_single():
    assert merge_sort([1]) == [1]
