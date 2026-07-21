import hashlib
import json
import time
from pathlib import Path
import numpy as np

def calculate_sha256(file_path: Path) -> str:
    """
    Computes a deterministic SHA-256 hash of the file contents.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
        
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read in 64kb chunks
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()

def save_embedding_and_metadata(
    output_dir: Path,
    audio_path: Path,
    embedding: np.ndarray,
    metadata_info: dict,
    model_path: Path,
    warnings: list[str] = None,
    source_path: str = None
) -> tuple[Path, Path]:
    """
    Saves the aggregated L2-normalized track embedding as a .npy file
    and its corresponding metadata as a .json file, using the audio file's
    SHA-256 hash as the deterministic filename.
    
    Returns:
        npy_path: Path to the saved numpy file.
        json_path: Path to the saved json metadata file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    audio_path = Path(audio_path)
    sha256 = calculate_sha256(audio_path)
    
    npy_path = output_dir / f"{sha256}.npy"
    json_path = output_dir / f"{sha256}.json"
    
    # Save the embedding as a compressed numpy file (.npy)
    np.save(npy_path, embedding)
    
    # Prepare metadata dictionary
    stat = audio_path.stat()
    metadata = {
        "source_path": source_path if source_path is not None else str(audio_path.resolve()),
        "source_filename": audio_path.name,
        "file_size": stat.st_size,
        "file_mtime": stat.st_mtime,
        "sha256": sha256,
        "audio_duration": metadata_info["duration"],
        "embedding_model_name": "EffnetDiscogs",
        "model_filename": model_path.name,
        "embedding_dimensions": metadata_info["dimensions"],
        "extraction_timestamp": time.time(),
        "application_version": "0.1.0",
        "warnings": warnings or []
    }
    
    # Save the metadata as a formatted JSON file
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)
        
    return npy_path, json_path
