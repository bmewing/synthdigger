import unittest
import numpy as np

from music_embeddings.tagger import (
    _parse_embedding,
    assemble_label_matrix,
    TrackTagger,
)


class TestEmbeddingParsing(unittest.TestCase):

    def test_parses_pgvector_string(self):
        vec = _parse_embedding("[0.1,0.2,0.3]")
        self.assertEqual(vec.dtype, np.float32)
        self.assertTrue(np.allclose(vec, [0.1, 0.2, 0.3], atol=1e-6))

    def test_parses_python_list_fallback(self):
        vec = _parse_embedding([1.0, 2.0, 3.0])
        self.assertEqual(vec.dtype, np.float32)
        self.assertTrue(np.allclose(vec, [1.0, 2.0, 3.0]))


class TestLabelMatrix(unittest.TestCase):

    def _rows(self):
        # (sha256, embedding, group_id/artist, tags)
        return [
            ("a", [0.0, 0.0], 1, ["Rock", "Indie"]),
            ("b", [0.1, 0.1], 1, ["Rock"]),
            ("c", [0.2, 0.2], 2, ["Rock", "Jazz"]),
            ("d", [0.3, 0.3], 2, ["Ambient"]),        # Ambient is rare
            ("e", [0.4, 0.4], 3, []),                 # no inherited tags at all
        ]

    def test_min_support_filters_rare_tags(self):
        ds = assemble_label_matrix(self._rows(), "style", min_support=2)
        # Rock (3) and Indie(1)/Jazz(1)/Ambient(1): only Rock survives support>=2... Indie/Jazz/Ambient dropped
        self.assertEqual(ds.tags, ["Rock"])
        self.assertIn("Indie", ds.dropped_tags)
        self.assertIn("Jazz", ds.dropped_tags)
        self.assertIn("Ambient", ds.dropped_tags)
        self.assertEqual(ds.dropped_tags["Indie"], 1)

    def test_multi_hot_and_negatives(self):
        ds = assemble_label_matrix(self._rows(), "style", min_support=1)
        self.assertEqual(ds.n_tracks, 5)
        # tags sorted alphabetically
        self.assertEqual(ds.tags, ["Ambient", "Indie", "Jazz", "Rock"])
        rock = ds.tags.index("Rock")
        # a, b, c have Rock; d, e do not
        self.assertTrue(np.array_equal(ds.Y[:, rock], np.array([1, 1, 1, 0, 0], dtype=np.uint8)))
        # track "e" with no tags is retained as an all-negative row
        self.assertEqual(ds.Y[4].sum(), 0)

    def test_groups_preserved(self):
        ds = assemble_label_matrix(self._rows(), "style", min_support=1)
        self.assertTrue(np.array_equal(ds.groups, np.array([1, 1, 2, 2, 3], dtype=np.int64)))

    def test_X_shape_and_dtype(self):
        ds = assemble_label_matrix(self._rows(), "style", min_support=1)
        self.assertEqual(ds.X.shape, (5, 2))
        self.assertEqual(ds.X.dtype, np.float32)

    def test_invalid_tag_type_still_assembles(self):
        # assemble_label_matrix does not validate tag_type (that is _label_query's job);
        # it simply records the label. Ensure it stores whatever it is given.
        ds = assemble_label_matrix(self._rows(), "mood", min_support=1)
        self.assertEqual(ds.tag_type, "mood")


class TestEstimator(unittest.TestCase):

    def test_linear_probe_fits_and_predicts_multilabel(self):
        # Two well-separated clusters, two independent labels -> probe should learn them.
        rng = np.random.RandomState(0)
        n = 60
        X = np.vstack([
            rng.normal(loc=+2.0, scale=0.2, size=(n, 4)),
            rng.normal(loc=-2.0, scale=0.2, size=(n, 4)),
        ]).astype(np.float32)
        Y = np.zeros((2 * n, 2), dtype=np.uint8)
        Y[:n, 0] = 1     # first cluster -> tag 0
        Y[n:, 1] = 1     # second cluster -> tag 1

        tagger = TrackTagger("style", ["tag0", "tag1"]).fit(X, Y)
        proba = tagger.predict_proba(X)
        self.assertEqual(proba.shape, (2 * n, 2))
        # first cluster should score higher on tag0 than tag1 on average
        self.assertGreater(proba[:n, 0].mean(), proba[:n, 1].mean())
        self.assertGreater(proba[n:, 1].mean(), proba[n:, 0].mean())


if __name__ == "__main__":
    unittest.main()
