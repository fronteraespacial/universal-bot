import tempfile
import unittest
from pathlib import Path

from universal_bot.locks import SingletonLock


class TestSingletonLock(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.lock_file = Path(self.tmp_dir.name) / "test.lock"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_acquire_and_release(self):
        lock1 = SingletonLock(self.lock_file)
        self.assertTrue(lock1.acquire())
        self.assertTrue(lock1.is_acquired)

        # Second acquire by another instance on same file must fail
        lock2 = SingletonLock(self.lock_file)
        self.assertFalse(lock2.acquire())
        self.assertFalse(lock2.is_acquired)

        # Release first lock
        lock1.release()
        self.assertFalse(lock1.is_acquired)

        # Now second acquire must succeed
        self.assertTrue(lock2.acquire())
        self.assertTrue(lock2.is_acquired)
        lock2.release()

    def test_context_manager(self):
        lock = SingletonLock(self.lock_file)
        with lock as acquired:
            self.assertTrue(acquired)
            self.assertTrue(lock.is_acquired)

        self.assertFalse(lock.is_acquired)


if __name__ == "__main__":
    unittest.main()
