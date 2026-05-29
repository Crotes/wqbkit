import logging
import sys
import urllib.parse
from datetime import datetime
from typing import Dict, List

import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import calinski_harabasz_score, silhouette_score
from sklearn.preprocessing import RobustScaler

sys.path.append("/home/worldquant/wqb/Code")

from wqbkit.app.core.alpha_base_core import AlphaBaseCore

API_BASE_URL = "https://api.worldquantbrain.com"
USERS_SELF_ALPHAS_URL = f"{API_BASE_URL}/users/self/alphas"
ALPHAS_URL = f"{API_BASE_URL}/alphas"
DEFAULT_LIMIT = 100
DEFAULT_OFFSET = 0
DEFAULT_REGION = "ASI"
TOTAL_SCORE = 100000
PCA_VARIANCE = 0.95
KMEANS_RANDOM_STATE = 42
COMPOSITE_SIL_WEIGHT = 0.4
COMPOSITE_CH_WEIGHT = 0.6
CH_SCALE = 100000
DEFAULT_MIN_CLUSTERS = 10
DEFAULT_MAX_CLUSTERS = 50

logger = logging.getLogger(__name__)


def get_history_alpha_ids(
    session: AlphaBaseCore,
    region: str,
    start_date: datetime,
    limit: int = DEFAULT_LIMIT,
    offset: int = DEFAULT_OFFSET,
) -> List[Dict[str, float]]:
    """
    从接口分页获取指定地区、指定日期后的alpha数据
    :param s: requests.Session对象，已完成登录的会话
    :param region: 地区大写：USA, EUR ... ...
    :param start_date: 过滤日期，获取该日期之后的因子
    :param limit: 每页获取的数量
    :param offset: 分页偏移量
    :return: 包含alpha的id和各类is指标的列表
    """
    alphas_data: List[Dict] = []
    start_date_str = urllib.parse.quote(start_date.astimezone().isoformat(timespec="seconds"))

    # 分页获取数据
    while True:
        url = (
            f"{USERS_SELF_ALPHAS_URL}?"
            f"limit={limit}&offset={offset}"
            f"&dateCreated%3E={start_date_str}"
            f"&settings.region={region}"
            f"&status!=UNSUBMITTED%1FIS-FAIL"
            f"&hidden=false"
            f"&order=-dateSubmitted"
        )

        try:
            resp = session.get(url)
            if resp.status_code != 200:
                logger.error(f"请求出错，状态码：{resp.status_code}")
                break

            data = resp.json()
            results = data.get("results", [])
            alphas_data.extend(results)

            if offset + len(results) >= data.get("count", 0) or len(results) < limit:
                break
            offset += limit

        except Exception as e:
            logger.error(f"数据获取异常，异常信息：{e}")
            break

    alpha_metrics: List[Dict[str, float]] = []
    for item in alphas_data:
        if item.get("type") != "REGULAR":
            continue
        is_data = item.get("is", {})
        metrics = {
            "id": item["id"],
            "fitness": is_data.get("fitness", 0.0),
            "longCount": is_data.get("longCount", 0.0),
            "shortCount": is_data.get("shortCount", 0.0),
            "turnover": is_data.get("turnover", 0.0),
            "returns": is_data.get("returns", 0.0),
            "drawdown": is_data.get("drawdown", 0.0),
            "margin": is_data.get("margin", 0.0),
            "sharpe": is_data.get("sharpe", 0.0),
        }
        alpha_metrics.append(metrics)

    if not alpha_metrics:
        logger.error("错误：没有获取到有效的alpha数据")
        return []

    return alpha_metrics


def determine_clusters_multi_criteria(
    X,
    min_clusters: int = DEFAULT_MIN_CLUSTERS,
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
) -> int:
    """
    多指标确定聚类数（结合轮廓系数、CH指数，同时限制聚类数范围）
    :param X: 标准化后的特征数据
    :param min_clusters: 最小聚类数（避免过少）
    :param max_clusters: 最大聚类数（避免过多）
    :return: 最终聚类数量
    """
    if len(X) <= min_clusters:
        return len(X)

    cluster_range = range(max(2, min_clusters), min(max_clusters + 1, len(X)))
    scores = []

    for k in cluster_range:
        kmeans = KMeans(n_clusters=k, random_state=KMEANS_RANDOM_STATE, n_init="auto")
        labels = kmeans.fit_predict(X)
        sil_score = silhouette_score(X, labels)
        ch_score = calinski_harabasz_score(X, labels)
        scores.append({
            "k": k,
            "sil": sil_score,
            "ch": ch_score,
            "composite": COMPOSITE_SIL_WEIGHT * sil_score + COMPOSITE_CH_WEIGHT * (ch_score / CH_SCALE),
        })

    score_df = pd.DataFrame(scores)
    best_k = score_df.sort_values("composite", ascending=False)["k"].iloc[0]

    best_k = max(min_clusters, min(best_k, max_clusters))
    return best_k


def cluster_alphas_improved(
    alpha_metrics: List[Dict[str, float]],
    use_pca: bool = True,
    cluster_algorithm: str = "kmeans",
) -> List[Dict[str, float]]:
    """
    改进的聚类逻辑：支持PCA降维、多种聚类算法、多指标确定聚类数
    :param alpha_metrics: alpha的指标数据
    :param use_pca: 是否使用PCA降维（处理特征冗余）
    :param cluster_algorithm: 聚类算法（kmeans/agglomerative/dbscan）
    :return: 选中的alpha列表（每个聚类fitness最大）
    """
    # 转换为DataFrame方便处理
    df = pd.DataFrame(alpha_metrics)

    feature_cols = ["longCount", "shortCount", "turnover", "returns", "drawdown", "margin", "sharpe"]

    X = df[feature_cols].fillna(0).values

    scaler = RobustScaler()
    X_scaled = scaler.fit_transform(X)

    if use_pca and len(feature_cols) > 2:
        pca = PCA(n_components=PCA_VARIANCE, random_state=KMEANS_RANDOM_STATE)
        X_processed = pca.fit_transform(X_scaled)
        logger.info(f"PCA降维后，特征维度从{len(feature_cols)}变为{X_processed.shape[1]}")
    else:
        X_processed = X_scaled

    best_k = determine_clusters_multi_criteria(
        X_processed,
        min_clusters=DEFAULT_MIN_CLUSTERS,
        max_clusters=DEFAULT_MAX_CLUSTERS,
    )
    logger.info(f"改进后确定的最佳聚类数量：{best_k}")

    if cluster_algorithm == "kmeans":
        cluster_model = KMeans(n_clusters=best_k, random_state=KMEANS_RANDOM_STATE, n_init="auto")
        df["cluster"] = cluster_model.fit_predict(X_processed)
    elif cluster_algorithm == "agglomerative":
        cluster_model = AgglomerativeClustering(n_clusters=best_k)
        df["cluster"] = cluster_model.fit_predict(X_processed)
    elif cluster_algorithm == "dbscan":
        cluster_model = DBSCAN(eps=0.5, min_samples=5)
        df["cluster"] = cluster_model.fit_predict(X_processed)
        noise_cluster = df["cluster"].max() + 1
        df.loc[df["cluster"] == -1, "cluster"] = noise_cluster
        best_k = len(df["cluster"].unique())
        logger.info(f"DBSCAN聚类后实际聚类数量：{best_k}")
    else:
        logger.error(f"不支持的聚类算法: {cluster_algorithm}")
        return []

    selected_alphas = []
    for cluster in df["cluster"].unique():
        cluster_df = df[df["cluster"] == cluster]
        best_alpha = cluster_df.loc[cluster_df["fitness"].idxmax()]
        selected_alphas.append(best_alpha.to_dict())

    return selected_alphas


if __name__ == "__main__":
    advisor_date = datetime(2025, 4, 19)
    page_limit = DEFAULT_LIMIT
    page_offset = DEFAULT_OFFSET
    target_region = DEFAULT_REGION

    core = AlphaBaseCore()

    alpha_metrics_list = get_history_alpha_ids(
        session=core,
        region=target_region,
        start_date=advisor_date,
        limit=page_limit,
        offset=page_offset,
    )

    if not alpha_metrics_list:
        logger.error("程序终止：未获取到有效alpha数据")
        sys.exit(1)

    selected_alpha_list = cluster_alphas_improved(
        alpha_metrics=alpha_metrics_list,
        use_pca=True,
        cluster_algorithm="kmeans",
    )

    if not selected_alpha_list:
        logger.error("程序终止：聚类后未选中任何alpha")
        sys.exit(1)

    total_selected = len(selected_alpha_list)
    per_alpha_weight = 1.0 / total_selected if total_selected > 0 else 0.0
    total_allocated_score = 0

    for alpha_info in selected_alpha_list:
        alpha_score = int(per_alpha_weight * TOTAL_SCORE)
        logger.info(
            f"Alpha ID：{alpha_info['id']} | "
            f"Fitness值：{alpha_info['fitness']} | "
            f"所属聚类：{alpha_info['cluster']} | "
            f"分配分数：{alpha_score}"
        )
        update_url = f"{ALPHAS_URL}/{alpha_info['id']}"
        core.wqbs.patch(update_url, json={"osmosisPoints": alpha_score})
        total_allocated_score += alpha_score

    score_deviation = TOTAL_SCORE - total_allocated_score
    if score_deviation != 0:
        logger.info(f"因四舍五入产生分数偏差：{score_deviation}分，已将偏差分加到第一个Alpha上")
        first_alpha_score = int(per_alpha_weight * TOTAL_SCORE) + score_deviation
        logger.info(f"第一个Alpha {selected_alpha_list[0]['id']} 的最终分数：{first_alpha_score}")
        total_allocated_score = TOTAL_SCORE

    logger.info(f"分数分配完成：总分配分数 {total_allocated_score} 分，无分数损耗")
