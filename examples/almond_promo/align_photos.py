"""Register each photoreal image onto its Blender source (SIFT + RANSAC similarity) so collage wipes line up.
Writes hf/aligned/<name>.png at 2560x1440 and reports residuals."""
import cv2, numpy as np, os, json

WORK = r"C:\Users\liang\Documents\almond_promo"
PAIRS = [('look_golden', 'golden_v2b'), ('look_noon', 'morning_v2'), ('look_bluehour_on', 'bluehour_v3'), ('look_neon_night', 'neon_v3'), ('look_golden', 'bluehour_v3'), ('look_golden', 'neon_v3')]
os.makedirs(os.path.join(WORK, 'hf', 'aligned'), exist_ok=True)
sift = cv2.SIFT_create(6000)
report = {}
for src_name, ai_name in PAIRS:
    src = cv2.imread(os.path.join(WORK, 'blender', src_name + '_2560.png'))
    ai = cv2.resize(cv2.imread(os.path.join(WORK, 'hf', ai_name + '.png')), (2560, 1440), interpolation=cv2.INTER_AREA)
    g1 = cv2.createCLAHE(3.0, (8, 8)).apply(cv2.cvtColor(src, cv2.COLOR_BGR2GRAY))
    g2 = cv2.createCLAHE(3.0, (8, 8)).apply(cv2.cvtColor(ai, cv2.COLOR_BGR2GRAY))
    k1, d1 = sift.detectAndCompute(g1, None)
    k2, d2 = sift.detectAndCompute(g2, None)
    m = cv2.BFMatcher().knnMatch(d2, d1, k=2)
    good = [a for a, b in m if a.distance < 0.72 * b.distance]
    p2 = np.float32([k2[a.queryIdx].pt for a in good]); p1 = np.float32([k1[a.trainIdx].pt for a in good])
    M, inl = cv2.estimateAffinePartial2D(p2, p1, method=cv2.RANSAC, ransacReprojThreshold=6, maxIters=20000, confidence=0.999)
    n_in = int(inl.sum())
    Hm, inlh = cv2.findHomography(p2, p1, cv2.USAC_MAGSAC, 5.0, maxIters=20000, confidence=0.999)
    use_h = Hm is not None and int(inlh.sum()) > n_in * 1.5
    s = float(np.hypot(M[0, 0], M[1, 0])); rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    res = np.linalg.norm((p2[inl[:, 0] == 1] @ M[:, :2].T + M[:, 2]) - p1[inl[:, 0] == 1], axis=1)
    if use_h:
        warped = cv2.warpPerspective(ai, Hm, (2560, 1440), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        ph = cv2.perspectiveTransform(p2[inlh[:, 0] == 1][None], Hm)[0]
        res = np.linalg.norm(ph - p1[inlh[:, 0] == 1], axis=1); n_in = int(inlh.sum())
    else:
        warped = cv2.warpAffine(ai, M, (2560, 1440), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    cv2.imwrite(os.path.join(WORK, 'hf', 'aligned', ai_name + '.png'), warped)
    report[ai_name] = dict(model='homography' if use_h else 'similarity', matches=len(good), inliers=n_in, scale=round(s, 4), rot_deg=round(rot, 3),
                           tx=round(float(M[0, 2]), 1), ty=round(float(M[1, 2]), 1), median_residual_px=round(float(np.median(res)), 2))
    print(ai_name, report[ai_name])
json.dump(report, open(os.path.join(WORK, 'hf', 'aligned', 'report.json'), 'w'), indent=1)
