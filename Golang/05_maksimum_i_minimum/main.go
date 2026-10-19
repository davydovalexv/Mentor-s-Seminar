package main

import "fmt"

func minMax(nums []int) (min, max int) {
	min, max = nums[0], nums[0]
	for _, x := range nums[1:] {
		if x < min {
			min = x
		}
		if x > max {
			max = x
		}
	}
	return min, max
}

func main() {
	nums, ok := readNumbers()
	if !ok {
		return
	}
	min, max := minMax(nums)
	fmt.Println("Минимум:", min)
	fmt.Println("Максимум:", max)
}

func readNumbers() ([]int, bool) {
	var n int
	fmt.Print("Количество чисел: ")
	if _, err := fmt.Scan(&n); err != nil || n < 1 {
		fmt.Println("Ошибка: количество должно быть целым числом больше 0")
		return nil, false
	}

	nums := make([]int, n)
	fmt.Printf("Введите %d чисел: ", n)
	for i := 0; i < n; i++ {
		if _, err := fmt.Scan(&nums[i]); err != nil {
			fmt.Println("Ошибка: ожидалось целое число")
			return nil, false
		}
	}
	return nums, true
}
