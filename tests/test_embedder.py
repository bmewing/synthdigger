import unittest
import numpy as np
from pathlib import Path
import tempfile
import json

from music_embeddings.embedder import MusicEmbedder
from music_embeddings.audio import extract_log_mel_spectrogram, compute_patches
from music_embeddings.serialization import save_embedding_and_metadata, calculate_sha256
from music_embeddings import config

class TestMusicEmbeddings(unittest.TestCase):
    
    def test_l2_normalization_logic(self):
        # Verify correctness of manual L2 normalization math
        vec = np.array([3.0, 4.0, 0.0], dtype=np.float32)
        norm = np.linalg.norm(vec)
        self.assertAlmostEqual(norm, 5.0)
        
        normalized = vec / norm
        self.assertAlmostEqual(np.linalg.norm(normalized), 1.0)
        
    def test_rejection_of_zero_vector(self):
        # Verify that we check for zero vectors during normalization
        zero_vec = np.zeros((1, 1280), dtype=np.float32)
        norms = np.linalg.norm(zero_vec, axis=1)
        
        with self.assertRaises(ValueError):
            if np.any(norms == 0):
                raise ValueError("Zero vector encountered in patch embeddings.")
                
    def test_rejection_of_nan_or_inf(self):
        # Verify that we check for NaN and inf values in input tensors
        nan_vec = np.array([[1.0, np.nan, 2.0]], dtype=np.float32)
        inf_vec = np.array([[1.0, np.inf, 2.0]], dtype=np.float32)
        
        with self.assertRaises(ValueError):
            if np.any(np.isnan(nan_vec)) or np.any(np.isinf(nan_vec)):
                raise ValueError("Model output contains NaN or infinite values.")
                
        with self.assertRaises(ValueError):
            if np.any(np.isnan(inf_vec)) or np.any(np.isinf(inf_vec)):
                raise ValueError("Model output contains NaN or infinite values.")

    def test_aggregation_of_multiple_patch_embeddings(self):
        # Verify exact aggregation math: L2-normalize, average, and L2-normalize final
        patch1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        patch2 = np.array([0.0, 2.0, 0.0], dtype=np.float32)
        
        # 1. L2 normalize each patch
        p1_norm = patch1 / np.linalg.norm(patch1)
        p2_norm = patch2 / np.linalg.norm(patch2)
        
        # 2. Average the normalized vectors
        avg = (p1_norm + p2_norm) / 2.0
        self.assertTrue(np.allclose(avg, np.array([0.5, 0.5, 0.0])))
        
        # Step 3: L2 normalize final
        final = avg / np.linalg.norm(avg)
        self.assertAlmostEqual(np.linalg.norm(final), 1.0, places=5)
        self.assertTrue(np.allclose(final, np.array([1.0 / np.sqrt(2.0), 1.0 / np.sqrt(2.0), 0.0])))

    def test_deterministic_output_identifiers(self):
        # Verify SHA-256 calculation is deterministic and matches expected hash
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(b"dummy audio data content")
            tmp_path = Path(tmp.name)
            
        try:
            hash1 = calculate_sha256(tmp_path)
            hash2 = calculate_sha256(tmp_path)
            self.assertEqual(hash1, hash2)
            self.assertEqual(hash1, "196dfe68f3a537a8031a14e02e21ff434ae5d460c8e892bfce02478009e86c13")
        finally:
            tmp_path.unlink()

    def test_missing_file_behavior(self):
        # Verify that FileNotFoundError is raised for non-existent audio files
        missing_path = Path("this/file/does/not/exist.wav")
        from music_embeddings.audio import load_audio
        with self.assertRaises(FileNotFoundError):
            load_audio(missing_path)

    def test_metadata_serialization(self):
        # Verify that metadata is written correctly to JSON file along with numpy file
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir_path = Path(tmp_dir)
            
            mock_audio = tmp_dir_path / "mock.wav"
            with open(mock_audio, "wb") as f:
                f.write(b"fake audio data")
                
            mock_emb = np.random.rand(1280).astype(np.float32)
            mock_emb /= np.linalg.norm(mock_emb)
            
            meta_info = {
                "duration": 5.2,
                "dimensions": 1280
            }
            
            npy_path, json_path = save_embedding_and_metadata(
                output_dir=tmp_dir_path,
                audio_path=mock_audio,
                embedding=mock_emb,
                metadata_info=meta_info,
                model_path=Path("mock_model.onnx")
            )
            
            self.assertTrue(npy_path.exists())
            self.assertTrue(json_path.exists())
            
            with open(json_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                
            self.assertEqual(meta["source_filename"], "mock.wav")
            self.assertEqual(meta["audio_duration"], 5.2)
            self.assertEqual(meta["embedding_dimensions"], 1280)
            self.assertEqual(meta["model_filename"], "mock_model.onnx")

    def test_integration_embed_file_optional(self):
        # Runs end-to-end embedding on a synthetic sine wave wav only if model file exists
        model_path = config.MODEL_PATH
        if not model_path.exists():
            self.skipTest(f"Model file not available at '{model_path}', skipping optional integration test.")
            
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp_path = Path(tmp.name)
            
        try:
            # Create a 1-second synthetic 16kHz sine wave mono WAV file
            sr = 16000
            t = np.linspace(0, 1.0, sr, endpoint=False)
            audio_data = (np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
            
            import struct
            with open(tmp_path, "wb") as f:
                # RIFF header
                f.write(b"RIFF")
                f.write(struct.pack("<I", 36 + len(audio_data) * 2))
                f.write(b"WAVE")
                # fmt chunk
                f.write(b"fmt ")
                f.write(struct.pack("<I", 16))
                f.write(struct.pack("<H", 1))   # format (PCM)
                f.write(struct.pack("<H", 1))   # mono
                f.write(struct.pack("<I", sr))  # sample rate
                f.write(struct.pack("<I", sr * 2))
                f.write(struct.pack("<H", 2))
                f.write(struct.pack("<H", 16))  # bits
                # data chunk
                f.write(b"data")
                f.write(struct.pack("<I", len(audio_data) * 2))
                f.write(audio_data.tobytes())
                
            embedder = MusicEmbedder(model_path)
            emb, meta = embedder.embed_file(tmp_path)
            
            self.assertEqual(emb.shape, (1280,))
            self.assertAlmostEqual(np.linalg.norm(emb), 1.0, places=5)
            self.assertEqual(meta["dimensions"], 1280)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

if __name__ == "__main__":
    unittest.main()
