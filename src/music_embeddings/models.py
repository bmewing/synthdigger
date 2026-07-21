import urllib.request
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# URL of the dynamic batch size Discogs-EffNet model hosted by MTG-UPF
MODEL_URL = "https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs-effnet-bsdynamic-1.onnx"
JSON_URL = "https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs-effnet-bsdynamic-1.json"

def download_default_model(dest_path: Path) -> tuple[Path, Path]:
    """
    Downloads the default Discogs-EffNet ONNX model and its metadata json file.
    
    Returns:
        onnx_path: Path to the downloaded .onnx file
        json_path: Path to the downloaded .json class metadata file
    """
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    json_path = dest_path.with_suffix(".json")
    
    if not dest_path.exists():
        logger.info(f"Downloading model from {MODEL_URL} to {dest_path}...")
        try:
            urllib.request.urlretrieve(MODEL_URL, str(dest_path))
            logger.info("ONNX Model download completed successfully.")
        except Exception as e:
            raise RuntimeError(f"Failed to download ONNX model file: {e}")
            
    if not json_path.exists():
        logger.info(f"Downloading class metadata from {JSON_URL} to {json_path}...")
        try:
            urllib.request.urlretrieve(JSON_URL, str(json_path))
            logger.info("Class metadata JSON download completed successfully.")
        except Exception as e:
            raise RuntimeError(f"Failed to download class metadata JSON file: {e}")
            
    return dest_path, json_path

def load_class_labels(json_path: Path) -> list[str]:
    """
    Loads the 400 Discogs genre/style class labels from the JSON metadata file.
    """
    json_path = Path(json_path)
    if not json_path.exists():
        download_default_model(json_path.with_suffix(".onnx"))
        
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        classes = data.get("classes", [])
        if not classes:
            raise ValueError("No 'classes' array found in JSON metadata.")
        return classes
    except Exception as e:
        raise RuntimeError(f"Failed to load class labels from {json_path}: {e}")
