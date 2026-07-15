with open('D:\\work\\aiwork\\autoai\\test_output.txt', 'w') as f:
    try:
        from tests.quartic_solver import solve_quartic_ferrari
        f.write('Import successful\n')
        roots = solve_quartic_ferrari(2, 1, -4)
        f.write(f'Got {len(roots)} roots\n')
        for i, root in enumerate(roots):
            f.write(f'Root {i}: {root}\n')
    except Exception as e:
        f.write(f'Error: {type(e).__name__}: {e}\n')
        import traceback
        f.write(traceback.format_exc())
