from pathlib import Path
import time
import logging
import numpy as np
import onnxruntime as ort

from music_embeddings.audio import load_audio, extract_log_mel_spectrogram, compute_patches
from music_embeddings.models import load_class_labels

logger = logging.getLogger(__name__)

class MusicEmbedder:
    def __init__(self, model_path: Path) -> None:
        """
        Initializes the MusicEmbedder by loading the pretrained ONNX model.
        
        Args:
            model_path: Path to the .onnx model weights file.
        """
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model file not found at '{self.model_path}'. "
                "Please download the model file first (e.g. using the download-model command)."
            )
            
        # Load the ONNX session (forced to CPUExecutionProvider for cross-platform reliability)
        self.session = ort.InferenceSession(
            str(self.model_path),
            providers=["CPUExecutionProvider"]
        )
        
        # Determine input and output node names
        self.input_name = self.session.get_inputs()[0].name
        
        self.activations_output_name = None
        self.embedding_output_name = None
        
        for out in self.session.get_outputs():
            if out.name == "activations" or (out.shape and len(out.shape) == 2 and out.shape[1] == 400):
                self.activations_output_name = out.name
            elif out.name == "embeddings" or (out.shape and len(out.shape) == 2 and out.shape[1] == 1280):
                self.embedding_output_name = out.name
                
        if not self.embedding_output_name:
            self.embedding_output_name = self.session.get_outputs()[1].name
        if not self.activations_output_name:
            self.activations_output_name = self.session.get_outputs()[0].name
            
        # Load class labels (400 Discogs genre/style names)
        json_path = self.model_path.with_suffix(".json")
        try:
            self.class_labels = load_class_labels(json_path)
        except Exception as e:
            logger.warning(f"Could not load Discogs class labels from {json_path}: {e}")
            self.class_labels = [f"Class_{i}" for i in range(400)]
            
        logger.info(f"Loaded ONNX model from {self.model_path}")
        logger.info(
            f"Input: '{self.input_name}', Activations: '{self.activations_output_name}', "
            f"Embedding: '{self.embedding_output_name}'"
        )

    def embed_and_predict_file(self, audio_path: Path, max_seconds: float = None) -> tuple[np.ndarray, dict, dict[str, float]]:
        """
        Loads, preprocesses, and extracts both the track embedding vector
        and the 400 Discogs genre/style probabilities for an audio file.
        
        Returns:
            final_embedding: L2-normalized 1D float32 array of shape (1280,).
            metadata_info: Dict containing audio duration, patch count, and processing time.
            genre_probabilities: Dict mapping genre/style name -> float probability (0.0 to 1.0).
        """
        start_time = time.time()
        audio_path = Path(audio_path)
        
        # 1. Load and decode audio
        y, duration = load_audio(audio_path, max_seconds=max_seconds)
        
        # 2. Extract log-mel spectrogram
        log_mel = extract_log_mel_spectrogram(y)
        
        # 3. Generate patches of shape [num_patches, 128, 96]
        patches = compute_patches(log_mel)
        num_patches = len(patches)
        if num_patches == 0:
            raise ValueError(f"Audio file '{audio_path.name}' is too short or produced zero patches.")
            
        # 4. Run model inference for BOTH activations (genre logits) and embeddings
        outputs = self.session.run(
            [self.activations_output_name, self.embedding_output_name],
            {self.input_name: patches}
        )
        activations = outputs[0]        # shape: [num_patches, 400]
        patch_embeddings = outputs[1]   # shape: [num_patches, 1280]
        
        # Validate returned shapes
        if len(patch_embeddings.shape) != 2 or patch_embeddings.shape[1] != 1280:
            raise ValueError(f"Unexpected embedding output shape: {patch_embeddings.shape}")
        if np.any(np.isnan(patch_embeddings)) or np.any(np.isinf(patch_embeddings)):
            raise ValueError("Model output contains NaN or infinite values.")
            
        # 5. L2-normalize patch embeddings
        norms = np.linalg.norm(patch_embeddings, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("Zero vector encountered in patch embeddings (cannot normalize).")
        normalized_patches = patch_embeddings / norms
        
        # 6. Aggregate: average temporal patch embeddings
        track_embedding = np.mean(normalized_patches, axis=0)
        track_norm = np.linalg.norm(track_embedding)
        if track_norm == 0 or np.isnan(track_norm) or np.isinf(track_norm):
            raise ValueError("Aggregated track embedding is zero or invalid.")
        final_embedding = track_embedding / track_norm
        
        # 7. Discogs genre probabilities are output directly as activated probabilities in [0.0, 1.0]
        # Average probability across all temporal patches
        track_probs = np.mean(activations, axis=0)
        
        genre_probabilities = {
            label: float(prob)
            for label, prob in zip(self.class_labels, track_probs)
        }
        
        processing_time = time.time() - start_time
        metadata_info = {
            "duration": duration,
            "num_patches": num_patches,
            "processing_time": processing_time,
            "dimensions": final_embedding.shape[0]
        }
        
        return final_embedding, metadata_info, genre_probabilities

    def embed_file(self, audio_path: Path, max_seconds: float = None) -> tuple[np.ndarray, dict]:
        """
        Loads, preprocesses, and extracts a single track-level embedding for the audio file.
        """
        embedding, metadata_info, _ = self.embed_and_predict_file(audio_path, max_seconds=max_seconds)
        return embedding, metadata_info
