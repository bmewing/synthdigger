import unittest

from music_embeddings.genre_selection import select_genres


class TestSelectGenres(unittest.TestCase):

    def test_peaked_track_keeps_few(self):
        # One dominant genre -> only it survives the relative threshold.
        pairs = [("Baroque", 0.96), ("Renaissance", 0.28), ("Opera", 0.17),
                 ("Choral", 0.03), ("Medieval", 0.01)]
        selected, uncl = select_genres(pairs)
        self.assertFalse(uncl)
        # threshold = max(0.05, 0.25*0.96=0.24) -> Baroque, Renaissance
        self.assertEqual([g for g, _ in selected], ["Baroque", "Renaissance"])

    def test_low_confidence_is_unclassifiable(self):
        # Flat/low distribution (silence, noise) -> zero genres.
        pairs = [("House", 0.035), ("Experimental", 0.029), ("Punk", 0.028)]
        selected, uncl = select_genres(pairs)
        self.assertTrue(uncl)
        self.assertEqual(selected, [])

    def test_eclectic_track_keeps_several_but_capped(self):
        # Many near-equal moderate probs -> several kept, but never over the cap.
        pairs = [(f"g{i}", 0.20 - i * 0.005) for i in range(30)]  # 0.20..0.055
        selected, uncl = select_genres(pairs, cap=10)
        self.assertFalse(uncl)
        self.assertLessEqual(len(selected), 10)
        self.assertGreater(len(selected), 3)

    def test_floor_cuts_diffuse_tail(self):
        pairs = [("A", 0.5), ("B", 0.2), ("C", 0.06), ("D", 0.04), ("E", 0.01)]
        selected, uncl = select_genres(pairs, frac=0.25, floor=0.05)
        # threshold = max(0.05, 0.125) = 0.125 -> A, B only
        self.assertEqual([g for g, _ in selected], ["A", "B"])

    def test_unsorted_input_is_handled(self):
        pairs = [("B", 0.2), ("A", 0.9), ("C", 0.05)]
        selected, uncl = select_genres(pairs)
        self.assertEqual(selected[0][0], "A")

    def test_empty_input(self):
        selected, uncl = select_genres([])
        self.assertTrue(uncl)
        self.assertEqual(selected, [])

    def test_top_genre_always_survives_when_confident(self):
        # Confident top but everything else tiny -> keep exactly the top.
        pairs = [("A", 0.5), ("B", 0.02), ("C", 0.01)]
        selected, uncl = select_genres(pairs)
        self.assertFalse(uncl)
        self.assertEqual([g for g, _ in selected], ["A"])


if __name__ == "__main__":
    unittest.main()
