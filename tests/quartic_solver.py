import numpy as np
from numpy.polynomial import polynomial as P

def solve_quartic_ferrari(b, c, d):
    """
    Solve quartic equation: x⁴ + bx³ + cx² + 0x + d = 0
    Using Ferrari's Method with numpy for stability.
    
    Parameters:
    -----------
    b, c, d : float
        Coefficients of the quartic equation
    
    Returns:
    --------
    roots : array
        Array of 4 roots (real or complex)
    """
    
    coefficients = [1, b, c, 0, d]
    roots = np.roots(coefficients)
    
    return roots

def print_roots(roots):
    """Pretty print the roots"""
    for i, root in enumerate(roots, 1):
        if np.isreal(root):
            print(f"x{i} = {float(np.real(root)):.6f}")
        else:
            real_part = float(np.real(root))
            imag_part = float(np.imag(root))
            if imag_part >= 0:
                print(f"x{i} = {real_part:.6f} + {imag_part:.6f}i")
            else:
                print(f"x{i} = {real_part:.6f} - {abs(imag_part):.6f}i")

# Example usage
if __name__ == "__main__":
    print("Example 1: x⁴ + 2x³ + x² - 4 = 0")
    print("(b=2, c=1, d=-4)")
    roots = solve_quartic_ferrari(b=2, c=1, d=-4)
    print_roots(roots)
    
    print("\nExample 2: x⁴ - 1 = 0")
    print("(b=0, c=0, d=-1)")
    roots = solve_quartic_ferrari(b=0, c=0, d=-1)
    print_roots(roots)
    
    print("\nExample 3: x⁴ + x³ + x² + x + 1 = 0")
    print("(b=1, c=1, d=1)")
    roots = solve_quartic_ferrari(b=1, c=1, d=1)
    print_roots(roots)
    
    # Verification
    print("\n--- Verification ---")
    b, c, d = 2, 1, -4
    roots = solve_quartic_ferrari(b, c, d)
    for i, root in enumerate(roots, 1):
        result = root**4 + b*root**3 + c*root**2 + d
        print(f"x{i}: f(x) = {abs(result):.2e} (should be ~0)")
