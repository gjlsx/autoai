def compute_common_difference():
    nums = [55, 15, 45, 25, 35]
    sorted_nums = sorted(nums)
    # diff = sorted_nums[1] - sorted_nums[0]
    result = sorted_nums[1] - sorted_nums[0]
    print(f"agent: cline")
    print(f"tasks: t03181000.t6")
    print(f"results:")
    print(f"t03181000.t6={result}")
    print(f"subtotal={result}")

if __name__ == "__main__":
    compute_common_difference()
