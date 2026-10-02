package history

import (
	"fmt"
	"sync"
	"testing"
)

// BenchmarkProject measures synthetic projection only; it excludes SQL and IPC.
func BenchmarkProject(b *testing.B) {
	for _, size := range []int{100, 1000, 10000} {
		dataset := make([]Fact, size)
		for i := range dataset {
			dataset[i] = Fact{PlatformID: fmt.Sprintf("00000000-0000-0000-0000-%012x", i+1), State: "pending", CreatedAt: "2026-10-01T00:00:00+00:00", UpdatedAt: "2026-10-01T00:00:00"}
		}
		for _, page := range []int{21, 100} {
			for _, concurrency := range []int{1, 10, 50} {
				b.Run(fmt.Sprintf("history%d/page%d/concurrency%d", size, page, concurrency), func(b *testing.B) {
					req := ProjectionRequest{Version: 1, RequestID: "00000000-0000-0000-0000-000000000064", Query: Query{Limit: page}, Facts: dataset[:page]}
					if _, err := Project(req); err != nil {
						b.Fatal(err)
					}
					b.ReportAllocs()
					b.ResetTimer()
					var wg sync.WaitGroup
					wg.Add(concurrency)
					for worker := 0; worker < concurrency; worker++ {
						go func(w int) {
							defer wg.Done()
							for i := w; i < b.N; i += concurrency {
								if _, err := Project(req); err != nil {
									b.Error(err)
								}
							}
						}(worker)
					}
					wg.Wait()
				})
			}
		}
	}
}
