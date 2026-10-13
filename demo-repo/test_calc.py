import unittest

from calc import add, average, divide, subtract


class CalcTest(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(2, 3), 5)

    def test_subtract(self) -> None:
        self.assertEqual(subtract(5, 3), 2)

    def test_divide(self) -> None:
        self.assertEqual(divide(6, 3), 2)

    def test_average(self) -> None:
        self.assertEqual(average([1, 2, 3]), 2)


if __name__ == "__main__":
    unittest.main()
