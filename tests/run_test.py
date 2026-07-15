from tests.quartic_solver import solve_quartic_ferrari, print_roots

print("Example 1: x^4 + 2x^3 + x^2 - 4 = 0")
roots = solve_quartic_ferrari(b=2, c=1, d=-4)
print_roots(roots)

print("\nExample 2: x^4 - 1 = 0")
roots = solve_quartic_ferrari(b=0, c=0, d=-1)
print_roots(roots)

print("\nVerification - checking if solutions are correct:")
b, c, d = 2, 1, -4
roots = solve_quartic_ferrari(b, c, d)
for i, root in enumerate(roots, 1):
    result = root**4 + b*root**3 + c*root**2 + d
    print(f"x{i}: f(x) = {abs(result):.2e}")
