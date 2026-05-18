import pytest
from projectsa.selection_sort import selection_sort

def test_selection_sort_specific_array():
    input_arr = [45, 35, 74, 25, 81, 68, 98, 92, 48, 4]
    expected = [4, 25, 35, 45, 48, 68, 74, 81, 92, 98]
    assert selection_sort(input_arr) == expected

def test_selection_sort_empty():
    assert selection_sort([]) == []

def test_selection_sort_single():
    assert selection_sort([1]) == [1]
