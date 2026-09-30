"""4K registration of the interior frames onto the Blender living-room camera (features at 2560, warp at 3840)."""
import cv2, numpy as np, os, json

D = r"C:\Users\liang\Documents\almond_promo\interior"
OUT = os.path.join(D, 'aligned4k'); os.makedirs(OUT, exist_ok=True)
SRC = {'rhino_living': 'rhino_living_4k.png', 'photo_golden_a': 'photo_golden_a_4k.png', 'photo_morning': 'photo_morning_4k.png',
       'photo_bluehour': 'photo_bluehour_4k.png', 'photo_neon': 'photo_neon_4k.png'}
FW, FH, OW, OH = 2560, 1440, 3840, 2160
sift = cv2.SIFT_create(8000); clahe = cv2.createCLAHE(3.0, (8, 8))
ref = cv2.resize(cv2.imread(os.path.join(D, 'model_golden_4k.png')), (FW, FH), interpolation=cv2.INTER_AREA)
k1, d1 = sift.detectAndCompute(clahe.apply(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)), None)
rep = {}
for name, fn in SRC.items():
    full = cv2.imread(os.path.join(D, fn))
    small = cv2.resize(full, (FW, FH), interpolation=cv2.INTER_AREA)
    k2, d2 = sift.detectAndCompute(clahe.apply(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)), None)
    good = [a for a, b in cv2.BFMatcher().knnMatch(d2, d1, k=2) if a.distance < 0.72 * b.distance]
    p2 = np.float32([k2[a.queryIdx].pt for a in good]); p1 = np.float32([k1[a.trainIdx].pt for a in good])
    M, inl = cv2.estimateAffinePartial2D(p2, p1, method=cv2.RANSAC, ransacReprojThreshold=5, maxIters=20000, confidence=0.999)
    m = inl[:, 0] == 1
    res = np.linalg.norm(p2[m] @ M[:, :2].T + M[:, 2] - p1[m], axis=1)
    # lift the 2560-space similarity to full-res source -> 3840 output
    sx = FW / full.shape[1]; so = OW / FW
    A = np.vstack([M, [0, 0, 1]]) @ np.diag([sx, FH / full.shape[0], 1])
    A = np.diag([so, so, 1]) @ A
    cv2.imwrite(os.path.join(OUT, name + '.png'), cv2.warpAffine(full, A[:2], (OW, OH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT))
    rep[name] = dict(inliers=int(m.sum()), median_residual_px_2560=round(float(np.median(res)), 2))
    print(name, rep[name])
json.dump(rep, open(os.path.join(OUT, 'report.json'), 'w'), indent=1)
