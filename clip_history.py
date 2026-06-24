"""In-memory clipboard history ring buffer (pure logic, no Win32)."""


class ClipHistory:
    """Most-recent-first history of copied text snippets, capped at max_items.

    Adding text that is empty/whitespace-only, or identical to the newest entry,
    is ignored. Adding a duplicate that exists deeper in the list moves it to the
    front. Held in memory only.
    """

    def __init__(self, max_items=20):
        self.max_items = max_items
        self._items = []  # newest first

    def add(self, text):
        if not text or not text.strip():
            return False
        if self._items and self._items[0] == text:
            return False
        if text in self._items:
            self._items.remove(text)
        self._items.insert(0, text)
        del self._items[self.max_items:]
        return True

    def items(self):
        return list(self._items)

    def select(self, index):
        """Move the entry at index to the front (re-copy) and return it.

        Returns None for an out-of-range index.
        """
        if index < 0 or index >= len(self._items):
            return None
        text = self._items.pop(index)
        self._items.insert(0, text)
        return text

    def __len__(self):
        return len(self._items)
