import os
from pathlib import Path
import numpy as np
import librosa

def load_audio(audio_path: Path, target_sr: int = 16000, max_seconds: float = None) -> tuple[np.ndarray, float]:
    """
    Loads and decodes a local audio file, converting it to mono and resampling to target_sr.
    
    Args:
        audio_path: Path to the local audio file.
        target_sr: Sample rate to resample the audio to (defaults to 16000).
        max_seconds: Optional limit on the length of loaded audio in seconds.
        
    Returns:
        y: 1D float32 numpy array of audio samples.
        duration: Total duration of the loaded audio in seconds.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
        
    try:
        # librosa.load supports MP3, FLAC, M4A/AAC, and WAV via soundfile and audioread
        y, sr = librosa.load(str(audio_path), sr=target_sr, mono=True, duration=max_seconds)
    except Exception as e:
        raise RuntimeError(f"Failed to decode audio file {audio_path}: {e}")
        
    duration = len(y) / target_sr
    return y, duration

def extract_log_mel_spectrogram(y: np.ndarray, sr: int = 16000) -> np.ndarray:
    """
    Extracts log-mel spectrogram features matching Essentia's TensorflowInputMusiCNN.
    
    The preprocessing configuration:
        frameSize = 512
        hopSize = 256
        numberBands = 96
        sampleRate = 16000
        warpingFormula = "slaneyMel" (htk=False in librosa)
        weighting = "linear"
        normalize = "unit_tri" (norm='slaney' in librosa)
        type = "power" (power=2.0 in librosa)
        comp = log10(10000 * mel + 1)
        
    Args:
        y: 1D audio sample array.
        sr: Sample rate of the audio (defaults to 16000).
        
    Returns:
        log_mel: 2D numpy array of shape (n_frames, 96).
    """
    # Compute Mel spectrogram using librosa.
    # center=False matches Essentia's FrameCutter which does not pad the start of signal.
    mel_spec = librosa.feature.melspectrogram(
        y=y,
        sr=sr,
        n_fft=512,
        hop_length=256,
        n_mels=96,
        fmin=0.0,
        fmax=sr / 2.0,
        power=2.0,
        htk=False,
        norm='slaney',
        center=False
    )
    
    # Apply Essentia's shift and log10 compression: log10(10000 * mel + 1)
    log_mel = np.log10(10000.0 * mel_spec + 1.0)
    
    # Transpose from (96, n_frames) to (n_frames, 96) to match Essentia output
    return log_mel.T.astype(np.float32)

def compute_patches(log_mel: np.ndarray, patch_size: int = 128, patch_hop: int = 62) -> np.ndarray:
    """
    Slices the full log-mel spectrogram into overlapping patches of size (patch_size, 96).
    
    Args:
        log_mel: Full log-mel spectrogram array of shape (n_frames, 96).
        patch_size: Number of frames in a patch (defaults to 128).
        patch_hop: Step size between adjacent patches (defaults to 62).
        
    Returns:
        patches: 3D numpy array of shape (num_patches, patch_size, 96).
    """
    n_frames, n_mels = log_mel.shape
    
    # If the audio is too short to produce even a single patch, we zero-pad it
    if n_frames < patch_size:
        pad_width = patch_size - n_frames
        log_mel = np.pad(log_mel, ((0, pad_width), (0, 0)), mode='constant')
        n_frames = patch_size
        
    # Ensure patch_hop is valid
    step = patch_hop if patch_hop > 0 else patch_size
    
    patches = []
    start = 0
    while start + patch_size <= n_frames:
        patches.append(log_mel[start:start + patch_size, :])
        start += step
        
    return np.array(patches, dtype=np.float32)
