package main

import "fmt"

func main() {
	var balance float64
	fmt.Print("Начальный баланс: ")
	if _, err := fmt.Scan(&balance); err != nil || balance < 0 {
		fmt.Println("Ошибка: баланс должен быть неотрицательным числом")
		return
	}

	for {
		fmt.Println("1. Посмотреть баланс")
		fmt.Println("2. Пополнить баланс")
		fmt.Println("3. Снять средства")
		fmt.Println("4. Выход")
		fmt.Print("Выберите операцию: ")

		var choice int
		if _, err := fmt.Scan(&choice); err != nil {
			fmt.Println("Ошибка: введите номер операции")
			return
		}

		switch choice {
		case 1:
			fmt.Printf("Баланс: %.2f\n", balance)
		case 2:
			amount, ok := readAmount("Сумма пополнения: ")
			if !ok {
				return
			}
			if amount <= 0 {
				fmt.Println("Ошибка: сумма должна быть положительной")
				continue
			}
			balance += amount
			fmt.Printf("Счёт пополнен на %.2f. Баланс: %.2f\n", amount, balance)
		case 3:
			amount, ok := readAmount("Сумма снятия: ")
			if !ok {
				return
			}
			if amount <= 0 {
				fmt.Println("Ошибка: сумма должна быть положительной")
				continue
			}
			if amount > balance {
				fmt.Printf("Недостаточно средств. Баланс: %.2f\n", balance)
				continue
			}
			balance -= amount
			fmt.Printf("Выдано %.2f. Баланс: %.2f\n", amount, balance)
		case 4:
			fmt.Printf("Операция завершена. Баланс: %.2f\n", balance)
			return
		default:
			fmt.Println("Нет такой операции")
		}
	}
}

func readAmount(prompt string) (float64, bool) {
	var amount float64
	fmt.Print(prompt)
	if _, err := fmt.Scan(&amount); err != nil {
		fmt.Println("Ошибка: введите число")
		return 0, false
	}
	return amount, true
}
