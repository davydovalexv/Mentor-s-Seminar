package main

import "fmt"

func main() {
	var n int
	fmt.Print("Количество чисел: ")
	if _, err := fmt.Scan(&n); err != nil || n < 1 {
		fmt.Println("Ошибка: количество должно быть целым числом больше 0")
		return
	}

	fmt.Printf("Введите %d чисел: ", n)

	var (
		sum        int
		min        int
		max        int
		even       int
		odd        int
		hasNumbers bool
	)
	for i := 0; i < n; i++ {
		var x int
		if _, err := fmt.Scan(&x); err != nil {
			fmt.Println("Ошибка: ожидалось целое число")
			return
		}
		if !hasNumbers {
			min, max = x, x
			hasNumbers = true
		} else if x < min {
			min = x
		} else if x > max {
			max = x
		}
		sum += x
		if x%2 == 0 {
			even++
		} else {
			odd++
		}
	}

	average := float64(sum) / float64(n)
	fmt.Println("Сумма:", sum)
	fmt.Printf("Среднее: %g\n", average)
	fmt.Println("Максимум:", max)
	fmt.Println("Минимум:", min)
	fmt.Println("Чётных:", even)
	fmt.Println("Нечётных:", odd)
}
