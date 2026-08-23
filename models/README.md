# Vendored model weights

## `face_detection_yunet_2023mar.onnx`

| | |
|---|---|
| Size | 232,589 bytes |
| SHA-256 | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` |
| Source | [`opencv/opencv_zoo`](https://github.com/opencv/opencv_zoo), `models/face_detection_yunet` |
| Model licence | MIT, © Shiqi Yu |
| Used by | `tower/world_builder/redaction.py` |

**Why this file is in the repository rather than a dependency.** The
detector itself — `cv2.FaceDetectorYN` — is already compiled into the
`opencv-python-headless` this project ships. Only the weights were
missing, and 227 KB of MIT-licensed data is a far smaller commitment than
any package that provides the same capability: `mediapipe` pulls
`opencv-contrib-python` alongside our headless build (the collision this
project already rejected `rapidocr_onnxruntime` for), and
`facenet-pytorch` downgrades torch, torchvision, numpy and pillow.

Vendoring also makes the capability reproducible and offline. A Tower
without network access still redacts.

**To verify:**

```
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('models/face_detection_yunet_2023mar.onnx').read_bytes()).hexdigest())"
```

**To replace or remove it:** delete the file, or point
`TOWER_FACE_REDACTION_MODEL` elsewhere. World Builder reports redaction as
unavailable with a reason rather than failing, and sessions record
`redaction: "none"` — which stays honest.
