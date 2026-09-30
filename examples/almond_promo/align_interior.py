"""Register the interior frames (Rhino capture + photoreal passes) onto the Blender living-room camera.
Similarity fit (SIFT + RANSAC); writes interior/aligned/<name>.png (2560x1440) and report.json."""
import cv2, numpy as np, os, json

D = r"C:\Users\liang\Documents\almond_promo\interior"
REF = 'model_golden.png'
NAMES = ['rhino_living', 'photo_golden_a', 'photo_morning', 'photo_bluehour', 'photo_neon']
os.makedirs(os.path.join(D, 'aligned'), exist_ok=True)
sift = cv2.SIFT_create(8000)
clahe = cv2.createCLAHE(3.0, (8, 8))
ref = cv2.imread(os.path.join(D, REF))
g1 = clahe.apply(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY))
k1, d1 = sift.detectAndCompute(g1, None)
report = {}
for n in NAMES:
    im = cv2.resize(cv2.imread(os.path.join(D, n + '.png')), (2560, 1440), interpolation=cv2.INTER_AREA)
    k2, d2 = sift.detectAndCompute(clahe.apply(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)), None)
    good = [a for a, b in cv2.BFMatcher().knnMatch(d2, d1, k=2) if a.distance < 0.72 * b.distance]
    p2 = np.float32([k2[a.queryIdx].pt for a in good]); p1 = np.float32([k1[a.trainIdx].pt for a in good])
    M, inl = cv2.estimateAffinePartial2D(p2, p1, method=cv2.RANSAC, ransacReprojThreshold=5, maxIters=20000, confidence=0.999)
    m = inl[:, 0] == 1
    res = np.linalg.norm(p2[m] @ M[:, :2].T + M[:, 2] - p1[m], axis=1)
    cv2.imwrite(os.path.join(D, 'aligned', n + '.png'),
                cv2.warpAffine(im, M, (2560, 1440), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT))
    report[n] = dict(matches=len(good), inliers=int(m.sum()), scale=round(float(np.hypot(M[0, 0], M[1, 0])), 4),
                     tx=round(float(M[0, 2]), 1), ty=round(float(M[1, 2]), 1), median_residual_px=round(float(np.median(res)), 2))
    print(n, report[n])
json.dump(report, open(os.path.join(D, 'aligned', 'report.json'), 'w'), indent=1)
