package main

import "fmt"

func countSigns(nums []int) (positive, negative, zeros int) {
	for _, x := range nums {
		if x > 0 {
			positive++
		} else if x < 0 {
			negative++
		} else {
			zeros++
		}
	}
	return positive, negative, zeros
}

func main() {
	var n int
	fmt.Print("Количество чисел: ")
	if _, err := fmt.Scan(&n); err != nil || n < 1 {
		fmt.Println("Ошибка: количество должно быть целым числом больше 0")
		return
	}

	nums := make([]int, n)
	fmt.Printf("Введите %d чисел: ", n)
	for i := 0; i < n; i++ {
		if _, err := fmt.Scan(&nums[i]); err != nil {
			fmt.Println("Ошибка: ожидалось целое число")
			return
		}
	}

	positive, negative, zeros := countSigns(nums)
	fmt.Println("Положительных:", positive)
	fmt.Println("Отрицательных:", negative)
	fmt.Println("Нулей:", zeros)
}
