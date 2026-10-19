package main

import "fmt"

func signName(n int) string {
	switch {
	case n > 0:
		return "положительное"
	case n < 0:
		return "отрицательное"
	default:
		return "ноль"
	}
}

func parityName(n int) string {
	if n%2 == 0 {
		return "чётное"
	}
	return "нечётное"
}

func yesNo(ok bool) string {
	if ok {
		return "да"
	}
	return "нет"
}

func main() {
	var n int
	fmt.Print("Введите целое число: ")
	if _, err := fmt.Scan(&n); err != nil {
		fmt.Println("Ошибка: введите целое число")
		return
	}

	fmt.Println("Знак:", signName(n))
	fmt.Println("Чётность:", parityName(n))
	fmt.Println("Делится на 3:", yesNo(n%3 == 0))
	fmt.Println("Делится на 5:", yesNo(n%5 == 0))
	fmt.Println("Делится на 3 и на 5:", yesNo(n%3 == 0 && n%5 == 0))
}
