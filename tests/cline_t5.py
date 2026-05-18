def task_t5():
    digits = "5318"
    return sum(int(d) for d in digits if int(d) % 2 != 0)
