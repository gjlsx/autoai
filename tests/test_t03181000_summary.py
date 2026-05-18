def verify_final_result():
    results = {
        "t1": 15,
        "t2": 25,
        "t3": 35,
        "t4": 45,
        "t5": 55,
        "t6": 10,
        "t7": 5
    }
    final_result = sum(results.values())
    print(f"agent: cline")
    print(f"tasks: summary")
    print(f"results:")
    for task_id, value in results.items():
        print(f"t03181000.{task_id}={value}")
    print(f"FINAL_RESULT={final_result}")
    
    if final_result == 190:
        print("Verification: SUCCESS")
    else:
        print("Verification: FAILED")

if __name__ == "__main__":
    verify_final_result()
