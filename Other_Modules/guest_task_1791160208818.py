
import time
import random

n = 400
# Multiplicación matricial intensiva O(N^3)
A = [[random.random() for _ in range(n)] for _ in range(n)]
B = [[random.random() for _ in range(n)] for _ in range(n)]
C = [[0.0 for _ in range(n)] for _ in range(n)]

t0 = time.perf_counter()
for i in range(n):
    for k in range(n):
        aik = A[i][k]
        for j in range(n):
            C[i][j] += aik * B[k][j]
elapsed = time.perf_counter() - t0

ops = 2 * (n ** 3)
gflops = round((ops / max(1e-6, elapsed)) / 1e9, 4)
checksum = round(sum(C[i][i] for i in range(n)), 2)

print(f"BENCHMARK_RESULT: type=matrix_mult, size={n}, time={elapsed:.4f}s, gflops={gflops}, trace_checksum={checksum}")
