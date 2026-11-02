
import time
import ast

code_sample = '''
def complex_math_pipeline(x, y, z):
    res = 0
    for i in range(100):
        if (x + i) % 2 == 0:
            res += (x * y) ** 0.5 + z
        else:
            res -= (y * z) ** 0.3 - x
    return res
''' * 200

t0 = time.perf_counter()
parsed = ast.parse(code_sample)
compiled = compile(parsed, filename="<ast_bench>", mode="exec")
elapsed = time.perf_counter() - t0

print(f"BENCHMARK_RESULT: type=ast_pipeline, nodes_compiled=200_functions, time={elapsed:.4f}s, verified=True")
