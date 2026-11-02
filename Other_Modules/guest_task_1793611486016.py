
import time

limit = 1000000
t0 = time.perf_counter()
sieve = bytearray([1]) * (limit + 1)
sieve[0] = sieve[1] = 0
for i in range(2, int(limit**0.5) + 1):
    if sieve[i]:
        sieve[i*i : limit+1 : i] = bytearray(len(range(i*i, limit+1, i)))
primes_count = sum(sieve)
elapsed = time.perf_counter() - t0
rate = round(limit / max(1e-6, elapsed) / 1e6, 2)

print(f"BENCHMARK_RESULT: type=prime_sieve, limit={limit}, primes_found={primes_count}, time={elapsed:.4f}s, throughput={rate} Mnum/s")
