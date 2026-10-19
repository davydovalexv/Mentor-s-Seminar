package main

import "fmt"

func isPrime(n int) bool {
	if n < 2 {
		return false
	}
	if n%2 == 0 {
		return n == 2
	}
	for d := 3; d <= n/d; d += 2 {
		if n%d == 0 {
			return false
		}
	}
	return true
}

func main() {
	var n int
	fmt.Print("Введите целое число: ")
	if _, err := fmt.Scan(&n); err != nil {
		fmt.Println("Ошибка: введите целое число")
		return
	}

	if isPrime(n) {
		fmt.Printf("%d — простое число\n", n)
		return
	}
	fmt.Printf("%d — не простое число\n", n)
}
