package main

import "fmt"

func main() {
	var n int
	fmt.Print("Введите N: ")
	if _, err := fmt.Scan(&n); err != nil || n < 1 {
		fmt.Println("Ошибка: N должно быть целым числом больше 0")
		return
	}

	var sum float64
	for i := 1; i <= n; i++ {
		sum += float64(i)
	}
	average := sum / float64(n)

	fmt.Printf("Сумма чисел от 1 до %d: %g\n", n, sum)
	fmt.Printf("Среднее значение: %g\n", average)
}
