import unittest
from ebayloader.book_research import extract_isbns, normalize_isbn, valid_isbn

class ISBNTests(unittest.TestCase):
    def test_isbn13_valid(self):
        self.assertTrue(valid_isbn("978-0-306-40615-7"))
    def test_isbn10_valid(self):
        self.assertTrue(valid_isbn("0-8044-2957-X"))
    def test_invalid_checksum(self):
        self.assertFalse(valid_isbn("9780306406158"))
    def test_normalize(self):
        self.assertEqual(normalize_isbn("978-0-306 40615-7"), "9780306406157")
    def test_extract(self):
        self.assertIn("9780306406157", extract_isbns("ISBN-13: 978-0-306-40615-7"))

if __name__ == "__main__":
    unittest.main()
