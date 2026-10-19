package main

import "fmt"

func calculate(a, b float64, op string) (float64, error) {
	switch op {
	case "+":
		return a + b, nil
	case "-":
		return a - b, nil
	case "*":
		return a * b, nil
	case "/":
		if b == 0 {
			return 0, fmt.Errorf("деление на ноль")
		}
		return a / b, nil
	default:
		return 0, fmt.Errorf("неизвестная операция %q", op)
	}
}

func main() {
	var a, b float64
	var op string

	fmt.Print("Первое число: ")
	if _, err := fmt.Scan(&a); err != nil {
		fmt.Println("Ошибка: введите число")
		return
	}

	fmt.Print("Операция (+, -, *, /): ")
	if _, err := fmt.Scan(&op); err != nil {
		fmt.Println("Ошибка: введите операцию")
		return
	}

	fmt.Print("Второе число: ")
	if _, err := fmt.Scan(&b); err != nil {
		fmt.Println("Ошибка: введите число")
		return
	}

	result, err := calculate(a, b, op)
	if err != nil {
		fmt.Println("Ошибка:", err)
		return
	}
	fmt.Printf("%g %s %g = %g\n", a, op, b, result)
}
