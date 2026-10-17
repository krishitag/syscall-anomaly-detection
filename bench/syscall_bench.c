// Tight syscall loop: measures per-syscall cost with and without tracing.
// Build static so it runs in the nginx image (no libc assumptions):
//   gcc -O2 -static -o bench/syscall_bench bench/syscall_bench.c
// usage: ./syscall_bench [iterations]
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>

int main(int argc, char **argv) {
    long n = (argc > 1) ? atol(argv[1]) : 5000000;
    struct timespec a, b;

    // warm up: fault in pages, settle the CPU
    for (long i = 0; i < 200000; i++) syscall(SYS_getpid);

    clock_gettime(CLOCK_MONOTONIC, &a);
    for (long i = 0; i < n; i++) syscall(SYS_getpid);
    clock_gettime(CLOCK_MONOTONIC, &b);

    double ns = (b.tv_sec - a.tv_sec) * 1e9 + (b.tv_nsec - a.tv_nsec);
    // machine-readable: iterations,total_ns,ns_per_syscall,syscalls_per_sec
    printf("%ld,%.0f,%.2f,%.0f\n", n, ns, ns / n, n / (ns / 1e9));
    return 0;
}
