import unittest

from app.services.document_limits import MAX_DOCUMENT_SIZE_BYTES


class DocumentLimitContractTests(unittest.TestCase):
    def test_limit_is_exactly_five_mebibytes(self):
        self.assertEqual(MAX_DOCUMENT_SIZE_BYTES, 5 * 1024 * 1024)

    def test_limit_boundary(self):
        self.assertLessEqual(5 * 1024 * 1024, MAX_DOCUMENT_SIZE_BYTES)
        self.assertGreater(5 * 1024 * 1024 + 1, MAX_DOCUMENT_SIZE_BYTES)


if __name__ == "__main__":
    unittest.main()
