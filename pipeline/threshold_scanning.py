"""Threshold scanning — 피처/임계값/조건 조합별 성능 지표 계산."""

from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
import numpy as np
import pandas as pd

import schema


def run_threshold_scanning(
    df: pd.DataFrame,
    features: list[str],
    target_col: str,
    thresholds: list[float] | None = None,
    conditions: list[str] | None = None,
) -> pd.DataFrame:
    """각 피처/임계값/조건 조합별 성능 지표 계산.

    Returns:
        DataFrame columns: feature, threshold, condition, roi, screen_rate, drop_rate, f1_score
        f1_score 내림차순 정렬
    """
    if thresholds is None:
        thresholds = schema.SCANNING_THRESHOLDS
    if conditions is None:
        conditions = schema.SCANNING_CONDITIONS

    # TODO: 실제 계산 로직은 루코드가 구현
    # 현재는 mock 데이터 반환
    # df에 존재하는 피처만 사용
    features = [f for f in features if f in df.columns]
    rng = np.random.default_rng(42)
    rows = []
    for feat in features:
        for thresh in thresholds:
            for cond in conditions:
                rows.append({
                    "feature": feat,
                    "threshold": thresh,
                    "condition": cond,
                    "roi": round(rng.uniform(0.5, 5.0), 3),
                    "screen_rate": round(rng.uniform(0.01, 0.5), 3),
                    "drop_rate": round(rng.uniform(0.01, 0.3), 3),
                    "f1_score": round(rng.uniform(0.3, 0.95), 3),
                })

    result = pd.DataFrame(rows)
    result = result.sort_values("f1_score", ascending=False).reset_index(drop=True)
    return result


def compute_prediction_metrics(
    df: pd.DataFrame,
    target_col: str,
    selections: list[dict],
) -> dict:
    """선택된 조건 조합으로 예측 지표 재계산.

    Args:
        df: 전처리된 데이터
        target_col: 타겟 컬럼명
        selections: [{"feature": str, "condition": str, "threshold": float}, ...]

    Returns:
        {"total": int, "screened": int, "screen_rate": float,
         "drop_rate": float, "roi": float, "f1_score": float}
    """
    # TODO: 실제 계산 로직은 루코드가 구현
    # 현재는 mock 데이터 반환
    # df에 존재하는 피처만 필터
    selections = [s for s in selections if s["feature"] in df.columns]
    if not selections or df is None or df.empty:
        return {
            "total": 0, "screened": 0,
            "screen_rate": 0.0, "drop_rate": 0.0, "roi": 0.0, "f1_score": 0.0,
        }

    n = len(df)
    rng = np.random.default_rng(hash(str(selections)) % 2**31)

    # mock: 조건 개수에 따라 screen_rate 변동
    base_screen = rng.uniform(0.05, 0.4)
    screened = max(1, int(n * base_screen))

    return {
        "total": n,
        "screened": screened,
        "screen_rate": round(screened / n, 4),
        "drop_rate": round(rng.uniform(0.01, 0.25), 4),
        "roi": round(rng.uniform(0.8, 5.0), 3),
        "f1_score": round(rng.uniform(0.4, 0.9), 3),
    }


def plot_feature_scatter(
    df: pd.DataFrame,
    target_col: str,
    selections: list[dict],
) -> bytes | None:
    """선택된 피처 조건에 따른 scatter plot 생성 (PNG bytes).

    - 1 피처: 1D scatter (x=피처, y=jitter)
    - 2 피처: 2D scatter
    - 3 피처: 3D scatter
    - 4+ 피처: None (그리지 않음)

    y=1인 점은 빨간색, y=0은 파란색. y=0을 먼저 그리고 y=1을 위에 그린다.
    각 피처의 임계값을 선으로 표시.
    """
    if df is None or df.empty or not selections:
        return None

    # 고유 피처만 추출 (순서 유지, df에 존재하는 컬럼만)
    seen = set()
    unique_selections = []
    for sel in selections:
        feat = sel["feature"]
        if feat not in seen and feat in df.columns:
            seen.add(feat)
            unique_selections.append(sel)

    if not unique_selections:
        return None

    n_features = len(unique_selections)
    if n_features > 3:
        return None

    y = df[target_col].values if target_col in df.columns else np.zeros(len(df))
    mask_pos = y == 1
    mask_neg = ~mask_pos

    fig = plt.figure(figsize=(8, 6))

    if n_features == 1:
        sel = unique_selections[0]
        feat = sel["feature"]
        thresh = sel["threshold"]
        cond = sel["condition"]
        x = df[feat].values

        ax = fig.add_subplot(111)
        jitter = np.random.default_rng(0).uniform(-0.1, 0.1, size=len(x))

        ax.scatter(x[mask_neg], jitter[mask_neg], c="royalblue", alpha=0.4, s=15, label="y=0")
        ax.scatter(x[mask_pos], jitter[mask_pos], c="red", alpha=0.7, s=20, label="y=1", zorder=5)
        ax.axvline(x=thresh, color="green", linestyle="--", linewidth=1.5, label=f"{feat} {cond} {thresh}")
        ax.set_xlabel(feat)
        ax.set_yticks([])
        ax.set_ylabel("")
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title(f"Feature: {feat} (threshold {cond} {thresh})")

    elif n_features == 2:
        sel0, sel1 = unique_selections[0], unique_selections[1]
        x = df[sel0["feature"]].values
        y_vals = df[sel1["feature"]].values

        ax = fig.add_subplot(111)
        ax.scatter(x[mask_neg], y_vals[mask_neg], c="royalblue", alpha=0.4, s=15, label="y=0")
        ax.scatter(x[mask_pos], y_vals[mask_pos], c="red", alpha=0.7, s=20, label="y=1", zorder=5)

        ax.axvline(x=sel0["threshold"], color="green", linestyle="--", linewidth=1.5,
                   label=f"{sel0['feature']} {sel0['condition']} {sel0['threshold']}")
        ax.axhline(y=sel1["threshold"], color="orange", linestyle="--", linewidth=1.5,
                   label=f"{sel1['feature']} {sel1['condition']} {sel1['threshold']}")

        ax.set_xlabel(sel0["feature"])
        ax.set_ylabel(sel1["feature"])
        ax.legend(loc="upper right", fontsize=8)
        ax.set_title(f"Features: {sel0['feature']} vs {sel1['feature']}")

    else:  # 3 features
        sel0, sel1, sel2 = unique_selections[0], unique_selections[1], unique_selections[2]
        x = df[sel0["feature"]].values
        y_vals = df[sel1["feature"]].values
        z = df[sel2["feature"]].values

        ax = fig.add_subplot(111, projection="3d")
        ax.scatter(x[mask_neg], y_vals[mask_neg], z[mask_neg], c="royalblue", alpha=0.3, s=15, label="y=0")
        ax.scatter(x[mask_pos], y_vals[mask_pos], z[mask_pos], c="red", alpha=0.7, s=20, label="y=1", zorder=5)

        # 임계값 평면을 선으로 표현
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        zlim = ax.get_zlim()

        # 피처 0 임계값: x 고정 평면 → y-z 평면의 사각형 테두리
        t0 = sel0["threshold"]
        ax.plot([t0, t0], ylim, [zlim[0], zlim[0]], color="green", linestyle="--", linewidth=1.5,
                label=f"{sel0['feature']} {sel0['condition']} {t0}")
        ax.plot([t0, t0], [ylim[0], ylim[0]], zlim, color="green", linestyle="--", linewidth=1.5)

        # 피처 1 임계값: y 고정 평면
        t1 = sel1["threshold"]
        ax.plot(xlim, [t1, t1], [zlim[0], zlim[0]], color="orange", linestyle="--", linewidth=1.5,
                label=f"{sel1['feature']} {sel1['condition']} {t1}")
        ax.plot([xlim[0], xlim[0]], [t1, t1], zlim, color="orange", linestyle="--", linewidth=1.5)

        # 피처 2 임계값: z 고정 평면
        t2 = sel2["threshold"]
        ax.plot(xlim, [ylim[0], ylim[0]], [t2, t2], color="purple", linestyle="--", linewidth=1.5,
                label=f"{sel2['feature']} {sel2['condition']} {t2}")
        ax.plot([xlim[0], xlim[0]], ylim, [t2, t2], color="purple", linestyle="--", linewidth=1.5)

        ax.set_xlabel(sel0["feature"])
        ax.set_ylabel(sel1["feature"])
        ax.set_zlabel(sel2["feature"])
        ax.legend(loc="upper right", fontsize=7)
        ax.set_title(f"Features: {sel0['feature']}, {sel1['feature']}, {sel2['feature']}")

    plt.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
