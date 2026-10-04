# MODEL_CARD fall_cls_v1

Non-clinical edge classifier. OpenCV cues still drive the care ladder; this ONNX is a
versioned artifact for later sibling consume PRs. Not a diagnosis.

## Artifact

- File: `models/fall_cls_v1.onnx`
- SHA256: `549721e2b29cad10776fde2cb6186cf19383f982050f37e9335096c1aaadb608`
- Input: `images` float32 NCHW, 3x32x32, BGR resize then /255
- Output: `scores` softmax `[no_fall, fall]`
- Stack: numpy-trained depthwise-separable CNN, ONNX opset 13, Apache-2.0 (OpenCV DNN)
- Train: balanced mini-batches, inverse-frequency class weights, val threshold baked into fall logit
- Default train code does not import Ultralytics or any AGPL package

## Data

- Family search: https://www.kaggle.com/datasets?search=fall&tags=13207-Computer+Vision
- Train slug (commercial-permissive, verified at download): `elwalyahmad/fall-detection`
- Eval-only slug: `uttejkumarkandagatla/fall-detection-dataset`
- Domain of this card: **kaggle**
- Image root: `/Users/pamu/Documents/GitHub/opencv-care-ladder-kaggle-retrain/datasets/elwalyahmad-fall-detection`
- Split: Video or subject ids were absent, so the split is per-frame (MODEL_CARD required note).
- Seed: 47
- Counts: train=743 val=159 test=159
- Written: 2026-10-04

## In-domain metrics

Target fall sensitivity: 0.85 (report target, not a hard ship gate).

| split | n | sensitivity | specificity | accuracy | confusion |
| --- | --- | --- | --- | --- | --- |
| train | 743 | 0.745 | 0.664 | 0.720 | tn=150 fp=76 fn=132 tp=385 |
| val | 159 | 0.730 | 0.729 | 0.730 | tn=35 fp=13 fn=30 tp=81 |
| test | 159 | 0.664 | 0.735 | 0.686 | tn=36 fp=13 fn=37 tp=73 |

In-domain Kaggle sensitivity is below the 0.85 target. Cause: small frame set, grouped split (no video leak), and a tiny edge CNN trained on CPU. Not a ship-blocking gate; see confusion matrix above.

## Cross-dataset

Cross-dataset eval on `uttejkumarkandagatla/fall-detection-dataset` (eval-only, not in the training mix): n=474 sensitivity=0.522 specificity=0.667 accuracy=0.582 confusion tn=132 fp=66 fn=132 tp=144. No ship threshold on this number.

## License

See `datasets/LICENSES.md`. Dataset bytes are gitignored. Weights in this file come only
from the fixture tree and/or a license-gated Kaggle train slug.

## How to retrain on Kaggle

```bash
export KAGGLE_CONFIG_DIR=$HOME/.kaggle   # directory that holds kaggle.json
pip install -e ".[train]"
python scripts/train_fall_cls.py --kaggle
```
