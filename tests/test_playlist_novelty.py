import unittest

import numpy as np

from music_embeddings.playlist import select_candidate_pool


class TestSelectCandidatePool(unittest.TestCase):

    def test_similar_returns_top_n_by_similarity(self):
        sims = np.array([0.1, 0.9, 0.5, 0.8, 0.2])
        pool = select_candidate_pool(sims, pool_size=2, novelty="similar")
        self.assertEqual(set(pool.tolist()), {1, 3})  # highest sims: idx1=0.9, idx3=0.8

    def test_different_returns_bottom_n_by_similarity(self):
        sims = np.array([0.1, 0.9, 0.5, 0.8, 0.2])
        pool = select_candidate_pool(sims, pool_size=2, novelty="different")
        self.assertEqual(set(pool.tolist()), {0, 4})  # lowest sims: idx0=0.1, idx4=0.2

    def test_step_away_returns_middle_band(self):
        sims = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        pool = select_candidate_pool(sims, pool_size=3, novelty="step_away")
        # descending order of sims is idx 8,7,6,...,0; middle 3 of that order are idx 5,4,3
        self.assertEqual(set(pool.tolist()), {3, 4, 5})

    def test_default_novelty_matches_similar(self):
        sims = np.array([0.3, 0.7, 0.1])
        default_pool = select_candidate_pool(sims, pool_size=2)
        similar_pool = select_candidate_pool(sims, pool_size=2, novelty="similar")
        self.assertEqual(set(default_pool.tolist()), set(similar_pool.tolist()))

    def test_pool_size_larger_than_array_is_clamped(self):
        sims = np.array([0.5, 0.1, 0.9])
        pool = select_candidate_pool(sims, pool_size=100, novelty="similar")
        self.assertEqual(len(pool), 3)

    def test_all_modes_return_requested_pool_size_without_duplicates(self):
        sims = np.linspace(0, 1, 20)
        for novelty in ("similar", "step_away", "different"):
            pool = select_candidate_pool(sims, pool_size=5, novelty=novelty)
            self.assertEqual(len(pool), 5)
            self.assertEqual(len(set(pool.tolist())), 5)


if __name__ == "__main__":
    unittest.main()
